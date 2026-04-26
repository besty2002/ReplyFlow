from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client, ClientOptions

from app.core.config import settings
from app.core.security import verify_supabase_jwt

# 토큰 추출용 Security Scheme
security = HTTPBearer()

def get_current_user_payload(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Authorization: Bearer <token> 에서 토큰을 뽑아내 검증 후 payload 반환"""
    tok = credentials.credentials
    return verify_supabase_jwt(tok)

def get_user_supabase_client(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Client:
    """
    사용자의 JWT를 Auth Header에 주입하여, 
    해당 사용자의 RLS(권한)가 적용된 Supabase 클라이언트를 생성 및 반환합니다.
    """
    token = credentials.credentials
    opts = ClientOptions(headers={"Authorization": f"Bearer {token}"})
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY, options=opts)

def get_current_user_context(
    payload: dict = Depends(get_current_user_payload),
    supabase: Client = Depends(get_user_supabase_client)
) -> dict:
    """
    DB를 조회하여 사용자가 속한 company_id 및 role(권한) 정보를 Context로 만들어 반환.
    이 Dependency를 라우터에 걸면, 로그인한 유저만 통과됨은 물론 RLS를 통과한 소속 정보까지 획득 가능.
    """
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="トークンにユーザーID情報が含まれていません。")

    # 주입된 클라이언트를 통해 RLS 통과 후 본인의 company_users 정보 질의
    res = supabase.table("company_users").select("company_id, role").eq("user_id", user_id).execute()
    
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="このユーザーはどの企業・組織にも属していないか、権한がありません。"
        )
        
    context = res.data[0]
    context["user_id"] = user_id
    return context
