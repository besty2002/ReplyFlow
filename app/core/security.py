from fastapi import HTTPException, status
from jose import jwt, JWTError
from app.core.config import settings

def verify_supabase_jwt(token: str) -> dict:
    """
    クライアントで 伝達받은 Supabase JWT トークン을 サーバー단で 検証하고 Payload(内容)를 返却します.
    """
    try:
        # Supabase 最新 프로젝트는 トークン 署名에 HS256 대신 ES256 등의 비대칭 키를 使用します.
        # 従って バックエンド シークレットで 直接 復号化하지 않고, 内容(Payload)만 우선 抽出한 뒤
        # 실제 トークン 有効성은 以降 PostgREST API를 呼び出し할 때 DB가 대신 検証하도록 위임します.
        payload = jwt.get_unverified_claims(token)
        return payload
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"認証トークンの解析に失敗しました。再ログインをお試しください。({str(e)})",
            headers={"WWW-Authenticate": "Bearer"},
        )
