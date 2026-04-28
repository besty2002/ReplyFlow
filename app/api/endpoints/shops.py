from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
from typing import Dict, Any, List
from pydantic import BaseModel

from app.api.dependencies import get_current_user_context, get_user_supabase_client

router = APIRouter()

class ShopCreate(BaseModel):
    platform: str
    shop_name: str
    api_key: str
    api_secret: str = ""

@router.get("/")
def get_connected_shops(
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    現在 ログ인된 계정(소속 会社)에 登録된 모든 다중 ショップ/プラットフォーム API 키 리스트를 불러옵니다.
    """
    company_id = user_context["company_id"]
    try:
        res = supabase_client.table("connected_shops").select("*").eq("company_id", company_id).order("created_at", desc=True).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/")
def add_connected_shop(
    shop_data: ShopCreate,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    라쿠텐, 야후 등 新しい ショップ몰 채널을 会社의 連携 리스트에 追加します.
    """
    company_id = user_context["company_id"]
    
    insert_data = {
        "company_id": company_id,
        "platform": shop_data.platform,
        "shop_name": shop_data.shop_name,
        "api_key": shop_data.api_key,
        "api_secret": shop_data.api_secret,
        "is_active": True
    }
    
    try:
        res = supabase_client.table("connected_shops").insert(insert_data).execute()
        return {"status": "success", "message": "新しい ショップ이 連携되었します.", "data": res.data[0] if res.data else None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ショップ 連携 失敗: {str(e)}")

@router.delete("/{shop_id}")
def delete_connected_shop(
    shop_id: str,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    既存 連携된 ショップ을 削除します.
    """
    company_id = user_context["company_id"]
    
    try:
        # 削除 処理 (RLS 덕분에 본인 会社가 아니면 クエリ 자체가 무시되지만, 명시적 안전성을 ために eq("company_id") 반영)
        supabase_client.table("connected_shops").delete().eq("id", shop_id).eq("company_id", company_id).execute()
        return {"status": "success", "message": "ショップ 連携이 해제되었します."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ショップの削除に失敗しました: {str(e)}")
