import httpx
import logging
import base64
import asyncio
from typing import Dict, Any, List
from app.core.config import settings

logger = logging.getLogger(__name__)

class YamatoClient:
    """
    ヤマト 운수(쿠로네코 멤버즈) Open API クライアントです.
    OIDC Discovery를 を通じて 運用 환경의 エンドポイント를 自動で 찾아 통신します.
    """
    
    def __init__(self, site_id: str = None, site_password: str = None):
        self.site_id = site_id or settings.YAMATO_SITE_ID
        self.site_password = site_password or settings.YAMATO_SITE_PASSWORD
        self.api_version = settings.YAMATO_API_VERSION
        
        # 基本 베이스 URL
        if settings.YAMATO_ENV == "prod":
            self.id_base_url = "https://id.kuronekoyamato.co.jp"
            self.api_base_url = "https://api.nrcs.kuronekoyamato.co.jp"
        else:
            self.id_base_url = "https://test-id.kuronekoyamato.co.jp"
            self.api_base_url = "https://dev03-api.nrcs.kuronekoyamato.co.jp"
        
        self.token_endpoint: str | None = None
        self.access_token: str | None = None

    async def discover_endpoints(self) -> bool:
        """
        OIDC Discovery를 を通じて 정확한 エンドポイント 주소를 가져옵니다.
        """
        discovery_url = f"{self.id_base_url}/.well-known/openid-configuration"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(discovery_url)
                if res.status_code == 200:
                    config = res.json()
                    self.token_endpoint = config.get("token_endpoint")
                    logger.info(f"🔍 [Yamato Discovery] トークン エンドポイント 발견: {self.token_endpoint}")
                    return True
                else:
                    # Discovery 失敗 시 デフォルト値 試行 (Gluu/oxAuth 표준 パス)
                    self.token_endpoint = f"{self.id_base_url}/oxauth/restv1/token"
                    logger.warning(f"⚠️ [Yamato Discovery] 失敗({res.status_code}), 基本 パス 使用: {self.token_endpoint}")
                    return True
        except Exception as e:
            # 타임아웃 등 발생 시 デフォルト値
            self.token_endpoint = f"{self.id_base_url}/oxauth/restv1/token"
            logger.error(f"🔥 [Yamato Discovery] 例外 발생: {e}, 基本 パス 使用")
            return True

    async def get_access_token(self) -> bool:
        """
        Client Credentials Flow를 使用하여 Access Token을 発行받します.
        """
        if not self.site_id or not self.site_password:
            logger.error("❌ [Yamato Auth] Site ID/Password 누락")
            return False

        if not self.token_endpoint:
            await self.discover_endpoints()

        # Basic Auth ヘッダー
        auth_str = f"{self.site_id}:{self.site_password}"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()
        
        headers = {
            "Authorization": f"Basic {encoded_auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "KuronekoYamato-API-VERSION": self.api_version
        }
        
        payload = {
            "grant_type": "client_credentials",
            "scope": "openid"
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(self.token_endpoint, headers=headers, data=payload)
                if res.status_code == 200:
                    data = res.json()
                    self.access_token = data.get("access_token")
                    logger.info("✅ [Yamato Auth] Access Token 発行 成功")
                    return True
                else:
                    logger.error(f"❌ [Yamato Auth] 失敗: {res.status_code} - {res.text}")
                    return False
        except Exception as e:
            logger.error(f"🔥 [Yamato Auth] 例外: {e}")
            return False

    async def get_tracking_by_order_number(self, order_number: str) -> Dict[str, Any]:
        """
        注文番号를 기반で ヤマト 실時間 追跡 情報를 가져옵니다.
        """
        if not self.access_token:
            if not await self.get_access_token():
                return {"status": "error", "message": "認証 失敗"}

        # 실제 API 呼び出し (パス는 사양서에 맞춰 유연하게 대응)
        # TODO: 실제 사양서 PDF의 'Search' または 'Shipment Status' パス 確認 필요
        url = f"{self.api_base_url}/v1/shipments/search" 
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "KuronekoYamato-API-VERSION": self.api_version,
            "Content-Type": "application/json"
        }
        
        # '記事' フィールド(비고란) 매칭 パラメータ (명세서에 に従い 'remarks' または 'note'로 修正 가능)
        payload = { "remarks": order_number }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                
                if res.status_code == 200:
                    data = res.json()
                    # ヤマト レスポンス パーシング (실제 사양 기반)
                    result = data.get("result") or data.get("shipment") or {}
                    if not result:
                        return {"status": "not_found", "message": "配送 データ 없음"}
                        
                    return {
                        "status": "success",
                        "tracking_number": result.get("slip_number") or result.get("tracking_id"),
                        "current_status": result.get("status_name") or result.get("status"),
                        "current_location": result.get("last_office_name") or result.get("location"),
                        "estimated_delivery": result.get("scheduled_date") or result.get("delivery_date"),
                    }
                else:
                    logger.warning(f"⚠️ [Yamato API] {res.status_code}: {res.text}")
                    return {"status": "error", "message": f"照会 失敗 ({res.status_code})"}
        except Exception as e:
            logger.error(f"🔥 [Yamato API] 例外: {e}")
            return {"status": "error", "message": "接続 エラー"}

yamato_client = YamatoClient()
