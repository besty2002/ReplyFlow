from fastapi import APIRouter, Depends
from typing import Dict, Any

from app.api.dependencies import get_current_user_context

router = APIRouter()

@router.get("/me")
def read_current_user(context: dict = Depends(get_current_user_context)) -> Dict[str, Any]:
    """
    현재 로그인된(JWT 헤더 소유자) 사용자의 소속 회사 정보와 Role 등을 반환합니다.
    기능 확인 목적 및 향후 클라이언트 UI 로그인 유지용 객체로 활용 가능.
    """
    return {
        "status": "success",
        "user_context": context
    }
