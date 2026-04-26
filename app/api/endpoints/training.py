from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from supabase import Client
from typing import Iterator
import json
from datetime import datetime
import io

from app.api.dependencies import get_current_user_context, get_user_supabase_client

router = APIRouter()

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
