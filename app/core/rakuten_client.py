import httpx
import asyncio
import logging
import base64
import uuid
import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class RakutenRMSClient:
    """
    라쿠텐 RMS API (최신 InquiryManagementAPI) 와 통신하는 클라이언트입니다.
    XML 대신 최신 JSON 포맷을 사용하며 inquirymng-api 엔드포인트를 호출합니다.
    """
    def __init__(self, service_secret: str, license_key: str):
        auth_str = f"{service_secret}:{license_key}"
        encoded_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        self.headers = {
            "Authorization": f"ESA {encoded_auth}",
            "Content-Type": "application/json; charset=utf-8"
        }
        # 최신 Inquiry Management API 엔드포인트
        self.base_url = "https://api.rms.rakuten.co.jp/es/1.0/inquirymng-api"

    async def get_inquiry_list(self) -> List[Dict[str, Any]]:
        """
        라쿠텐 RMS로부터 모든 페이지의 문의 목록을 수집합니다. (비동기 Pagination)
        """
        endpoint = "https://api.rms.rakuten.co.jp/es/1.0/inquirymng-api/inquiries"
        
        now = datetime.datetime.now()
        # [수정] 수집 기간을 30일로 확대 (4월 17일 등 과거 데이터 수집 목적)
        start_date = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")
        end_date = now.strftime("%Y-%m-%dT%H:%M:%S")
        
        all_inquiries = []
        current_page = 1
        total_pages = 1
        
        try:
            import asyncio
            async with httpx.AsyncClient(timeout=30.0) as client:
                while current_page <= total_pages:
                    params = {
                        "fromDate": start_date,
                        "toDate": end_date,
                        "limit": 50,
                        "page": current_page,
                        "noMerchantReply": "true" # [공식문서 적용] 미답변 문의 필터
                    }
                    logger.info(f"📡 [Rakuten API] ページ {current_page}/{total_pages} 非同期収集中...")
                    res = await client.get(endpoint, headers=self.headers, params=params)
                    
                    if res.status_code == 200:
                        json_data = res.json()
                        total_pages = json_data.get("totalPageCount", 1)
                        
                        inquiries = self._parse_json_inquiries(json_data)
                        all_inquiries.extend(inquiries)
                        
                        logger.info(f"✅ [Rakuten API] {current_page}ページ完了! (累계 {len(all_inquiries)}件)")
                        current_page += 1
                        
                        # 서버 이벤트 루프를 양보하여 다른 요청 처리 가능하게 함
                        await asyncio.sleep(0.1)
                    else:
                        logger.error(f"❌ [Rakuten API] {current_page}ページ失敗: {res.text}")
                        break
                
                logger.info(f"🏁 [Rakuten API] 全量収集完了! 合計 {len(all_inquiries)}件 確保")
                return all_inquiries
        except Exception as e:
            logger.error(f"❌ [Rakuten API - NEW JSON] 연결 실패: {e}")
            return []

    async def send_reply(self, inquiry_id: str, shop_id: str, reply_text: str) -> bool:
        """
        지정된 문의에 답변을 발송합니다.
        공식 문서: POST https://api.rms.rakuten.co.jp/es/1.0/inquirymng-api/inquiry/reply
        """
        endpoint = f"{self.base_url}/inquiry/reply"
        payload = {
            "inquiryNumber": inquiry_id,
            "shopId": str(shop_id),
            "message": reply_text
        }
        
        try:
            logger.info(f"📤 [Rakuten API] 문의 ID {inquiry_id} (Shop: {shop_id}) 에 답변 전송 중...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(endpoint, headers=self.headers, json=payload)
                
                if res.status_code in [200, 201]:
                    logger.info(f"✅ [Rakuten API] 답변 전송 성공: {inquiry_id}")
                    return True
                else:
                    logger.error(f"❌ [Rakuten API] 답변 전송 실패 ({res.status_code}): {res.text}")
                    return False
        except Exception as e:
            logger.error(f"❌ [Rakuten API] 발송 중 예외 발생: {e}")
            return False

    async def get_order_details(self, order_number: str) -> Dict[str, Any]:
        """
        주문번호를 기반으로 라쿠텐 Order API v2.0에서 주문 상세 정보를 가져옵니다.
        URL: POST https://api.rms.rakuten.co.jp/es/2.0/order/getOrder
        """
        endpoint = "https://api.rms.rakuten.co.jp/es/2.0/order/getOrder"
        payload = {
            "orderNumberList": [order_number],
            "version": 7  # Rakuten API v2.0에서 필수 요구하는 버전 정보
        }
        
        try:
            logger.info(f"📡 [Rakuten Order API] 주문번호 {order_number} 상세 조회 시도...")
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(endpoint, headers=self.headers, json=payload)
                
                logger.info(f"📥 [Rakuten Order API] 응답 코드: {res.status_code}")
                if res.status_code == 200:
                    data = res.json()
                    # 대소문자 구분 없이 찾기 시도
                    order_list = data.get("OrderModelList") or data.get("orderModelList") or []
                    if order_list:
                        return order_list[0]
                    else:
                        logger.warning(f"⚠️ [Rakuten Order API] 주문 데이터를 찾을 수 없습니다: {data}")
                        return {}
                else:
                    logger.error(f"❌ [Rakuten Order API] 조회 실패: {res.text}")
                    return {}
        except Exception as e:
            logger.error(f"❌ [Rakuten Order API] 예외 발생: {e}")
            return {}

    def _parse_json_inquiries(self, json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        라쿠텐 최신 API 응답(json)에서 데이터를 추출합니다.
        """
        inquiries = []
        try:
            # [확인됨] 라쿠텐 최신 API는 'list'라는 키에 데이터를 담아줍니다.
            inquiry_list = json_data.get("list", [])
            logger.info(f"🔍 [Rakuten API] 응답 데이터 건수: {len(inquiry_list)}건 (상세 필터링 시작)")
            for item in inquiry_list:
                inq_no = str(item.get("inquiryNumber", "UNKNOWN"))
                
                # [초정밀 필터링]
                # 1. '완료' 상태(isCompleted=true)인 문의는 제외
                if item.get("isCompleted") is True:
                    logger.info(f"⏩ [Skip] 문의 {inq_no}: 완료(isCompleted=true) 상태임")
                    continue
                
                # 2. 이미 상점(merchant)에서 답변을 보낸 기록이 있는 경우 제외
                replies = item.get("replies", [])
                if any(r.get("replyFrom") == "merchant" for r in replies):
                    logger.info(f"⏩ [Skip] 문의 {inq_no}: 이미 상점 답변이 존재함")
                    continue
                
                # 라쿠텐 API 응답 오타(meessage) 및 정상(message) 대응
                content = item.get("meessage") or item.get("message") or ""
                
                inquiries.append({
                    "rakuten_inquiry_id": inq_no,
                    "customer_id": item.get("userName", "Anonymous"),
                    "title": "楽天 顧客問い合わせ", 
                    "content": content,
                    "received_at": item.get("regDate") or item.get("inquiryDateTime", ""),
                    "order_number": item.get("orderNumber"),
                    "item_name": item.get("itemName"),
                    "item_number": item.get("itemNumber"),
                    "category": item.get("category"),
                    "type": item.get("type")
                })
            return inquiries
        except Exception as e:
            logger.error(f"❌ [JSON Parsing] 실패: {e}")
            return []

    async def get_item_details(self, item_url: str) -> Dict[str, Any]:
        """
        [v2.0] 라쿠텐 Item API를 통해 상품의 상세 설정(배리에이션 매핑 등)을 가져옵니다.
        """
        endpoint = "https://api.rms.rakuten.co.jp/es/2.0/item/getItem"
        params = {"itemUrl": item_url}
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(endpoint, headers=self.headers, params=params)
                if res.status_code == 200:
                    return res.json().get("itemModel", {})
        except Exception as e:
            logger.error(f"🔥 [Rakuten Item API] 예외 발생: {e}")
            
        return {}

    async def get_variant_list(self, manage_number: str) -> List[str]:
        """
        [v2.1] 특정 상품(manageNumber)에 속한 모든 SKU(variantId) 목록을 가져옵니다.
        """
        if not manage_number:
            return []
            
        url = f"https://api.rms.rakuten.co.jp/es/2.1/inventories/variant-lists/manage-numbers/{manage_number.lower()}"
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, headers=self.headers)
                if res.status_code == 200:
                    data = res.json()
                    return data.get("variantList", [])
        except Exception as e:
            logger.error(f"🔥 [Rakuten Variant List] 예외 발생: {e}")
            
        return []

    async def get_inventory_external(self, manage_number: str, variant_id: str) -> Optional[int]:
        """
        [v2.1] 라쿠텐 Inventory API를 통해 특정 SKU의 현재 가용 재고를 조회합니다.
        429(QPS 초과) 에러 발생 시 1초 대기 후 최대 1회 재시도합니다.
        """
        if not manage_number or not variant_id:
            return None

        manage_number = manage_number.lower()
        url = f"https://api.rms.rakuten.co.jp/es/2.1/inventories/manage-numbers/{manage_number}/variants/{variant_id}"
        
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.get(url, headers=self.headers)
                    
                    if res.status_code == 200:
                        data = res.json()
                        logger.info(f"📊 [Inventory Debug] 응답 데이터: {data}")
                        # v2.1 규격: inventoryCount 필드 사용 (혹은 quantity 확인)
                        count = data.get("inventoryCount")
                        if count is None:
                            count = data.get("quantity") # 하위 호환성 체크
                        return count
                    elif res.status_code == 429:
                        if attempt == 0:
                            logger.warning(f"⚠️ [Rakuten Inventory] QPS 초과 (429). 1초 후 재시도합니다... ({manage_number}/{variant_id})")
                            await asyncio.sleep(1)
                            continue
                        else:
                            logger.error(f"❌ [Rakuten Inventory] QPS 초과 지속: {res.text}")
                    elif res.status_code == 404:
                        logger.warning(f"⚠️ [Rakuten Inventory v2.1] 존재하지 않는 SKU: {manage_number}/{variant_id}")
                        return None
                    else:
                        logger.error(f"❌ [Rakuten Inventory v2.1] 오류: {res.status_code} {res.text}")
                        return None
            except Exception as e:
                logger.error(f"🔥 [Rakuten Inventory v2.1] 예외 발생: {e}")
                return None
        
        return None
