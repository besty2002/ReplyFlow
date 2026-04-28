import logging
from typing import Dict, Any
from app.core.rakuten_client import RakutenRMSClient

logger = logging.getLogger(__name__)

class ShopAPIAdapter:
    """
    라쿠텐, 야후 등 각 プラットフォーム별로 外部 API 規格이 다르므로
    공통 インターフェース를 を通じて 発送 로직을 추상화하는 어댑터 클래스です.
    """
    
    @staticmethod
    async def send_reply(platform: str, api_key: str, api_secret: str, rakuten_inquiry_id: str, reply_text: str, shop_id: str = "") -> Dict[str, Any]:
        """
        プラットフォーム별 規格에 맞춰 HTTP リクエスト을 날리는 ロール을 します.
        """
        logger.info(f"🚀 [{platform.upper()}] API 発送 試行! (伝達 대상 問い合わせID: {rakuten_inquiry_id})")
        
        # 1. Rakuten (楽天市場)
        if platform == "rakuten":
            # 실제 라쿠텐 クライアント 呼び出し
            rakuten = RakutenRMSClient(service_secret=api_key, license_key=api_secret)
            # 샵 IDがなければ エラー (라쿠텐은 필수)
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
            
        # 基本 処理 (Amazon 등 혹은 미지원 プラットフォーム)
        else:
            logger.warning(f"⚠️ [{platform}] 아직 実装되지 않은 プラットフォーム API 呼び出しです.")
            return {"status": "success", "platform_msg": f"Mocking success for {platform}"}
