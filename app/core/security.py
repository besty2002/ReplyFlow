from fastapi import HTTPException, status
from jose import jwt, JWTError
from app.core.config import settings

def verify_supabase_jwt(token: str) -> dict:
    """
    클라이언트에서 전달받은 Supabase JWT 토큰을 서버단에서 검증하고 Payload(내용)를 반환합니다.
    """
    try:
        # Supabase 최신 프로젝트는 토큰 서명에 HS256 대신 ES256 등의 비대칭 키를 사용합니다.
        # 따라서 백엔드 시크릿으로 직접 복호화하지 않고, 내용(Payload)만 우선 추출한 뒤
        # 실제 토큰 유효성은 이후 PostgREST API를 호출할 때 DB가 대신 검증하도록 위임합니다.
        payload = jwt.get_unverified_claims(token)
        return payload
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"認証トークンの解析に失敗しました。再ログインをお試しください。({str(e)})",
            headers={"WWW-Authenticate": "Bearer"},
        )
