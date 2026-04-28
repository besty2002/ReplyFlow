import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from supabase import Client
from typing import Iterator, List, Optional
from pydantic import BaseModel

from app.api.dependencies import get_current_user_context, get_user_supabase_client

router = APIRouter()

class ReviewUpdate(BaseModel):
    corrected_answer: Optional[str] = None
    corrected_category: Optional[str] = None
    corrected_sentiment: Optional[str] = None
    review_note: Optional[str] = None
    is_training_ready: bool = True
    quality_score: float = 1.0

@router.get("/export/jsonl")
def export_training_data_jsonl(
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    아직 추출되지 않은 AI 학습 로그를 JSONL 포맷(프롬프트-응답 쌍)으로 반환합니다.
    호출 후 해당 레코드들은 추출 완료 처리되며, 이력(training_exports)이 생성됩니다.
    """
    company_id = user_context["company_id"]
    user_id = user_context["user_id"]
    
    # 1. 미추출 학습 데이터 조회
    res = supabase_client.table("ai_training_logs").select("*").eq("company_id", company_id).eq("is_exported", False).execute()
    
    records = res.data
    if not records:
        raise HTTPException(status_code=404, detail="새롭게 추출할 학습 데이터가 없습니다. 새로운 문의/승인을 먼저 진행해주세요.")
        
    # 2. JSONL 포맷 생성 스트림
    def iterfile() -> Iterator[str]:
        for rec in records:
            # 기본 jsonl 규격 (메시지 형태 적용 가능하지만 기본 prompt-completion 사용)
            item = {
                "prompt": rec["question"],
                "completion": rec["final_answer"]
            }
            # ensure_ascii=False로 두어 한글/일본어 깨짐 방지
            yield json.dumps(item, ensure_ascii=False) + "\n"
            
    # 3. 데이터 상태 업데이트 및 이력 로깅
    record_ids = [rec["id"] for rec in records]
    
    try:
        # Supabase를 통해 is_exported를 True로 변경
        supabase_client.table("ai_training_logs").update({
            "is_exported": True
        }).in_("id", record_ids).execute()
        
        # training_exports 테이븛에 이력 추가
        supabase_client.table("training_exports").insert({
            "company_id": company_id,
            "record_count": len(records),
            "file_format": "jsonl",
            "exported_by": user_id
        }).execute()
        
    except Exception as e:
        # 실패하더라도 일단 로깅만 하고 다운로드는 허용하도록 할 수 있지만 보수적으로 에러 발생
        raise HTTPException(status_code=500, detail=f"데이터 상태 업데이트 중 오류 발생: {str(e)}")
    
    # 4. 파일 다운로드 스트리밍 응답 (한글/일본어 지원)
    filename = f"training_data_{company_id[:8]}_{datetime.now().strftime('%Y%m%d%H%M')}.jsonl"
    return StreamingResponse(
        iterfile(),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            # CORS나 브라우저 다운로드 힌트를 위해 추가 지정
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )

@router.get("/reviews")
async def get_training_reviews(
    status: str = "pending",
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    검증 대기 중이거나 완료된 학습 리뷰 목록을 가져옵니다.
    """
    company_id = user_context["company_id"]
    
    query = supabase_client.table("training_reviews").select("*").eq("company_id", company_id)
    if status == "pending":
        query = query.eq("is_training_ready", False)
    elif status == "completed":
        query = query.eq("is_training_ready", True)
        
    res = query.order("created_at", desc=True).execute()
    return {"status": "success", "data": res.data}

@router.post("/reviews/{review_id}")
async def submit_review(
    review_id: str,
    review_data: ReviewUpdate,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    AI 답변을 검증하거나 수정하여 최종 학습 데이터로 승인합니다.
    """
    user_id = user_context["user_id"]
    company_id = user_context["company_id"]
    
    update_data = review_data.dict(exclude_unset=True)
    update_data["reviewed_by"] = user_id
    update_data["reviewed_at"] = datetime.utcnow().isoformat()
    
    try:
        res = supabase_client.table("training_reviews").update(update_data).eq("id", review_id).eq("company_id", company_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="리뷰 대상을 찾을 수 없습니다.")
        return {"status": "success", "data": res.data[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/logs/{log_id}/review")
async def create_review_from_log(
    log_id: str,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    특정 AI 처리 로그를 학습 검증 대상으로 등록합니다.
    """
    company_id = user_context["company_id"]
    
    # 1. 원본 로그 조회
    log_res = supabase_client.table("ai_training_logs").select("*").eq("id", log_id).eq("company_id", company_id).execute()
    if not log_res.data:
        raise HTTPException(status_code=404, detail="로그를 찾을 수 없습니다.")
    log = log_res.data[0]
    
    # 2. 이미 리뷰가 있는지 확인
    exist_res = supabase_client.table("training_reviews").select("id").eq("training_log_id", log_id).execute()
    if exist_res.data:
        return {"status": "success", "message": "이미 리뷰 등록됨", "review_id": exist_res.data[0]["id"]}
        
    # 3. 리뷰 생성
    review_data = {
        "company_id": company_id,
        "training_log_id": log_id,
        "inquiry_id": log["inquiry_id"],
        "original_question": log["question"],
        "original_ai_answer": log["final_answer"],
        "original_category": log.get("category"),
        "is_training_ready": False
    }
    
    res = supabase_client.table("training_reviews").insert(review_data).execute()
    return {"status": "success", "data": res.data[0]}
