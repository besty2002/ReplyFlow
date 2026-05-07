from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client, ClientOptions
from typing import Optional

from app.core.config import settings
from app.core.security import verify_supabase_jwt

# 토큰 추출용 Security Scheme (auto_error=False로 설정하여 커스텀 에러 처리 허용)
security = HTTPBearer(auto_error=False)

def get_token_from_request(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    """헤더 또는 쿼리 파라미터에서 토큰을 추출합니다."""
    # 1. Authorization Header 확인
    if credentials:
        return credentials.credentials
    
    # 2. Query Parameter 확인 (이미지 프록시 등 대응)
    token = request.query_params.get("token")
    if token:
        return token
        
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증 토큰이 없습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )

def get_current_user_payload(token: str = Depends(get_token_from_request)) -> dict:
    """JWT 검증 후 payload 반환"""
    return verify_supabase_jwt(token)

def get_user_supabase_client(token: str = Depends(get_token_from_request)) -> Client:
    """유저의 JWT가 적용된 Supabase 클라이언트 생성"""
    opts = ClientOptions(headers={"Authorization": f"Bearer {token}"})
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY, options=opts)

def get_current_user_context(
    payload: dict = Depends(get_current_user_payload),
    supabase: Client = Depends(get_user_supabase_client)
) -> dict:
    """사용자의 소속 정보(company_id)와 권한을 포함한 컨텍스트 반환"""
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="토큰에 유저 ID가 포함되어 있지 않습니다.")

    res = supabase.table("company_users").select("company_id, role").eq("user_id", user_id).execute()
    
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="이 유저는 소속된 조직이 없거나 권한이 없습니다."
        )
        
    context = res.data[0]
    context["user_id"] = user_id
    return context
