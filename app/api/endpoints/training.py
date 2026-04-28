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
    아직 抽出되지 않은 AI 학습 ログ를 JSONL フォーマット(プロンプト-レスポンス 쌍)で 返却します.
    呼び出し 후 해당 レコード들은 抽出 完了 処理되며, 履歴(training_exports)이 生成されます.
    """
    company_id = user_context["company_id"]
    user_id = user_context["user_id"]
    
    # 1. 未抽出 학습 データ 照会
    res = supabase_client.table("ai_training_logs").select("*").eq("company_id", company_id).eq("is_exported", False).execute()
    
    records = res.data
    if not records:
        raise HTTPException(status_code=404, detail="新たに抽出する学習データがありません。新しいお問い合わせ/承認を先に行ってください。")
        
    # 2. JSONL フォーマット 生成 스트림
    def iterfile() -> Iterator[str]:
        for rec in records:
            # 基本 jsonl 規格 (メッセージ 形態 適用 가능しかし 基本 prompt-completion 使用)
            item = {
                "prompt": rec["question"],
                "completion": rec["final_answer"]
            }
            # ensure_ascii=False로 두어 한글/일본어 깨짐 방지
            yield json.dumps(item, ensure_ascii=False) + "\n"
            
    # 3. データ ステータス アップデート 및 履歴 ロギング
    record_ids = [rec["id"] for rec in records]
    
    try:
        # Supabase를 を通じて is_exported를 True로 変更
        supabase_client.table("ai_training_logs").update({
            "is_exported": True
        }).in_("id", record_ids).execute()
        
        # training_exports 테이븛에 履歴 追加
        supabase_client.table("training_exports").insert({
            "company_id": company_id,
            "record_count": len(records),
            "file_format": "jsonl",
            "exported_by": user_id
        }).execute()
        
    except Exception as e:
        # 失敗하더라도 일단 ロギング만 하고 ダウンロード는 허용하도록 できる지만 保守的で エラーが発生しました
        raise HTTPException(status_code=500, detail=f"データ状態更新中にエラーが発生しました: {str(e)}")
    
    # 4. ファイル ダウンロード ストリーミング レスポンス (한글/일본어 지원)
    filename = f"training_data_{company_id[:8]}_{datetime.now().strftime('%Y%m%d%H%M')}.jsonl"
    return StreamingResponse(
        iterfile(),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            # CORS나 브라우저 ダウンロード 힌트를 ために 追加 지정
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
    検証 待機 중이거나 完了된 학습 리뷰 リスト을 가져옵니다.
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
    AI 返信을 検証하거나 修正하여 最終 학습 データ로 承認します.
    """
    user_id = user_context["user_id"]
    company_id = user_context["company_id"]
    
    update_data = review_data.dict(exclude_unset=True)
    update_data["reviewed_by"] = user_id
    update_data["reviewed_at"] = datetime.utcnow().isoformat()
    
    try:
        res = supabase_client.table("training_reviews").update(update_data).eq("id", review_id).eq("company_id", company_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="レビュー対象が見つかりません。")
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
    특정 AI 処理 ログ를 학습 検証 대상で 登録します.
    """
    company_id = user_context["company_id"]
    
    # 1. 원본 ログ 照会
    log_res = supabase_client.table("ai_training_logs").select("*").eq("id", log_id).eq("company_id", company_id).execute()
    if not log_res.data:
        raise HTTPException(status_code=404, detail="ログが見つかりません。")
    log = log_res.data[0]
    
    # 2. 이미 리뷰가 있는지 確認
    exist_res = supabase_client.table("training_reviews").select("id").eq("training_log_id", log_id).execute()
    if exist_res.data:
        return {"status": "success", "message": "既にレビュー登録済み", "review_id": exist_res.data[0]["id"]}
        
    # 3. 리뷰 生成
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
