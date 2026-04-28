from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
from pydantic import BaseModel
from typing import Dict, Any

from app.api.dependencies import get_current_user_context, get_user_supabase_client

router = APIRouter()

class CompanyUpdate(BaseModel):
    name: str

class PasswordUpdate(BaseModel):
    password: str

@router.get("/profile")
def get_profile(
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    현재 사용자 및 소속 회사 정보를 반환합니다.
    """
    company_id = user_context["company_id"]
    user_id = user_context["user_id"]
    
    try:
        # 회사 정보 조회
        comp_res = supabase_client.table("companies").select("*").eq("id", company_id).execute()
        company_data = comp_res.data[0] if comp_res.data else {}
        
        # 유저 정보 (Auth API 사용)
        user_res = supabase_client.auth.get_user()
        
        return {
            "status": "success",
            "company": company_data,
            "user": {
                "id": user_id,
                "email": user_res.user.email if user_res.user else None,
                "role": user_context["role"]
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/company")
def update_company(
    data: CompanyUpdate,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    대표 회사 이름을 변경합니다. (관리자 전용)
    """
    if user_context["role"] not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="管理者権限が必要です。")
        
    company_id = user_context["company_id"]
    try:
        res = supabase_client.table("companies").update({"name": data.name}).eq("id", company_id).execute()
        return {"status": "success", "message": "会社名が更新されました。", "data": res.data[0] if res.data else None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"会社名の更新に失敗しました: {str(e)}")

@router.put("/password")
def update_password(
    data: PasswordUpdate,
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    사용자의 비밀번호를 변경합니다.
    """
    try:
        supabase_client.auth.update_user({"password": data.password})
        return {"status": "success", "message": "パスワードが正常に更新されました。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"パスワードの変更に失敗しました: {str(e)}")


class GuidelinesUpdate(BaseModel):
    guidelines: str


@router.put("/guidelines")
def update_guidelines(
    data: GuidelinesUpdate,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    会社のCS対応ガイドラインを保存します。（管理者専用）
    AI回答生成時にこのガイドラインが参照されます。
    """
    if user_context["role"] not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="管理者権限が必要です。")

    company_id = user_context["company_id"]
    try:
        res = supabase_client.table("companies").update({
            "cs_guidelines": data.guidelines
        }).eq("id", company_id).execute()
        char_count = len(data.guidelines)
        return {
            "status": "success",
            "message": f"ガイドラインが保存されました（{char_count}文字）",
            "char_count": char_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ガイドラインの保存に失敗しました: {str(e)}")
