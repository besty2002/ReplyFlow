from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client, ClientOptions

from app.core.config import settings
from app.core.security import verify_supabase_jwt

# トークン 抽出용 Security Scheme
security = HTTPBearer()

def get_current_user_payload(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Authorization: Bearer <token> で トークン을 뽑아내 検証 후 payload 返却"""
    tok = credentials.credentials
    return verify_supabase_jwt(tok)

def get_user_supabase_client(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Client:
    """
    ユーザー의 JWT를 Auth Header에 주입하여, 
    해당 ユーザー의 RLS(権限)가 適用된 Supabase クライアント를 生成 및 返却します.
    """
    token = credentials.credentials
    opts = ClientOptions(headers={"Authorization": f"Bearer {token}"})
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY, options=opts)

def get_current_user_context(
    payload: dict = Depends(get_current_user_payload),
    supabase: Client = Depends(get_user_supabase_client)
) -> dict:
    """
    DB를 照会하여 ユーザー가 속한 company_id 및 role(権限) 情報를 Context로 만들어 返却.
    이 Dependency를 라우터에 걸면, ログ인한 유저만 통과됨은 물론 RLS를 통과한 소속 情報まで 取得 가능.
    """
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="トークンにユーザーID情報が含まれていません。")

    # 주입된 クライアント를 を通じて RLS 통과 후 본인의 company_users 情報 질의
    res = supabase.table("company_users").select("company_id, role").eq("user_id", user_id).execute()
    
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="このユーザーはどの企業・組織にも属していないか、権한がありません。"
        )
        
    context = res.data[0]
    context["user_id"] = user_id
    return context
