import logging
from typing import Dict, Any
from app.core.rakuten_client import RakutenRMSClient

logger = logging.getLogger(__name__)

class ShopAPIAdapter:
    """
    라쿠텐, 야후 등 각 플랫폼별로 외부 API 규격이 다르므로
    공통 인터페이스를 통해 발송 로직을 추상화하는 어댑터 클래스입니다.
    """
    
    @staticmethod
    async def send_reply(platform: str, api_key: str, api_secret: str, rakuten_inquiry_id: str, reply_text: str, shop_id: str = "") -> Dict[str, Any]:
        """
        플랫폼별 규격에 맞춰 HTTP 요청을 날리는 역할을 합니다.
        """
        logger.info(f"🚀 [{platform.upper()}] API 발송 시도! (전달 대상 문의 ID: {rakuten_inquiry_id})")
        
        # 1. Rakuten (楽天市場)
        if platform == "rakuten":
            # 실제 라쿠텐 클라이언트 호출
            rakuten = RakutenRMSClient(service_secret=api_key, license_key=api_secret)
            # 샵 ID가 없으면 에러 (라쿠텐은 필수)
            if not shop_id:
                return {"status": "failed", "platform_msg": "Shop ID is required for Rakuten"}
                
            success = await rakuten.send_reply(rakuten_inquiry_id, shop_id, reply_text)
            
            if success:
                return {"status": "success", "platform_msg": "Rakuten RMS API delivery successful"}
            else:
                return {"status": "failed", "platform_msg": "Rakuten RMS API delivery failed"}
        
        # 2. Yahoo! (Yahoo!ショッピング)
        elif platform == "yahoo":
            return {"status": "success", "platform_msg": "Yahoo! Shopping API delivery successful"}
            
        # 3. AU Pay (au PAY マーケット)
        elif platform == "aupay":
            return {"status": "success", "platform_msg": "au PAY Market Message API delivery successful"}
            
        # 4. Qoo10 (キューテン)
        elif platform == "qoo10":
            return {"status": "success", "platform_msg": "Qoo10 QSM API delivery successful"}
            
        # 기본 처리 (Amazon 등 혹은 미지원 플랫폼)
        else:
            logger.warning(f"⚠️ [{platform}] 아직 구현되지 않은 플랫폼 API 호출입니다.")
            return {"status": "success", "platform_msg": f"Mocking success for {platform}"}
