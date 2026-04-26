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
    현재 로그인된 계정(소속 회사)에 등록된 모든 다중 숍/플랫폼 API 키 리스트를 불러옵니다.
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
    라쿠텐, 야후 등 새로운 쇼핑몰 채널을 회사의 연동 리스트에 추가합니다.
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
        return {"status": "success", "message": "새로운 숍이 연동되었습니다.", "data": res.data[0] if res.data else None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"숍 연동 실패: {str(e)}")

@router.delete("/{shop_id}")
def delete_connected_shop(
    shop_id: str,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    기존 연동된 숍을 삭제합니다.
    """
    company_id = user_context["company_id"]
    
    try:
        # 삭제 처리 (RLS 덕분에 본인 회사가 아니면 쿼리 자체가 무시되지만, 명시적 안전성을 위해 eq("company_id") 반영)
        supabase_client.table("connected_shops").delete().eq("id", shop_id).eq("company_id", company_id).execute()
        return {"status": "success", "message": "숍 연동이 해제되었습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"숍 삭제 실패: {str(e)}")
