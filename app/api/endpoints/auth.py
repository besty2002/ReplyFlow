from fastapi import APIRouter, Depends
from typing import Dict, Any

from app.api.dependencies import get_current_user_context

router = APIRouter()

@router.get("/me")
def read_current_user(context: dict = Depends(get_current_user_context)) -> Dict[str, Any]:
    """
    現在 ログ인된(JWT ヘッダー 소유자) ユーザー의 소속 会社 情報와 Role 등을 返却します.
    기능 確認 목적 및 향후 クライアント UI ログ인 維持용 객체로 活用 가능.
    """
    return {
        "status": "success",
        "user_context": context
    }
