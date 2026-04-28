from __future__ import annotations
import httpx
import asyncio
import logging
import base64
import uuid
import datetime
from typing import Dict, Any, List

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
        # 공유 HTTP 클라이언트 (TCP 연결 재사용으로 성능 향상)
        self._shared_client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """공유 HTTP 클라이언트를 반환합니다. 없으면 새로 생성합니다."""
        if self._shared_client is None or self._shared_client.is_closed:
            self._shared_client = httpx.AsyncClient(timeout=15.0, headers=self.headers)
        return self._shared_client

    async def close(self):
        """공유 HTTP 클라이언트를 닫습니다."""
        if self._shared_client and not self._shared_client.is_closed:
            await self._shared_client.aclose()
            self._shared_client = None

    async def get_inquiry_list(self) -> List[Dict[str, Any]]:
        """
        라쿠텐 RMS로부터 모든 페이지의 문의 목록을 수집합니다. (비동기 Pagination)
        """
        endpoint = "https://api.rms.rakuten.co.jp/es/1.0/inquirymng-api/inquiries"
        
        now = datetime.datetime.now()
        start_date = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")
        end_date = now.strftime("%Y-%m-%dT%H:%M:%S")
        
        all_inquiries = []
        current_page = 1
        total_pages = 1
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                while current_page <= total_pages:
                    params = {
                        "fromDate": start_date,
                        "toDate": end_date,
                        "limit": 50,
                        "page": current_page,
                        "noMerchantReply": "true",  # 公式API: 未返信のみ取得
                    }
                    print(f"  [API] ページ {current_page}/{total_pages} 未返信のみ取得中... ({start_date} ~ {end_date})", flush=True)
                    res = await client.get(endpoint, headers=self.headers, params=params)
                    
                    print(f"  [API] HTTP {res.status_code}", flush=True)
                    
                    if res.status_code == 200:
                        json_data = res.json()
                        total_pages = json_data.get("totalPageCount", 1)
                        raw_count = len(json_data.get("list", []))
                        print(f"  [API] 응답: totalPages={total_pages}, 현재 페이지 문의={raw_count}건", flush=True)
                        
                        inquiries = self._parse_json_inquiries(json_data)
                        all_inquiries.extend(inquiries)
                        
                        print(f"  [API] {current_page}ページ完了 (未返信 누계: {len(all_inquiries)}건)", flush=True)
                        current_page += 1
                        
                        await asyncio.sleep(0.1)
                    else:
                        print(f"  ❌ [API] HTTP {res.status_code}: {res.text[:200]}", flush=True)
                        break
                
                print(f"  [API] 수집 완료! 총 未返信 {len(all_inquiries)}건", flush=True)
                return all_inquiries
        except Exception as e:
            print(f"  ❌ [API] 연결 실패: {e}", flush=True)
            import traceback
            traceback.print_exc()
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
        라쿠텐 API 응답을 파싱합니다.
        UNICONA 未返信 = noMerchantReply(API) + isCompleted=false(파서)
        """
        inquiries = []
        skipped = 0
        try:
            inquiry_list = json_data.get("list", [])
            print(f"  [Parser] API 응답 {len(inquiry_list)}건 (isCompleted 필터 적용)", flush=True)
            
            for item in inquiry_list:
                inq_no = str(item.get("inquiryNumber", "UNKNOWN"))
                
                # isCompleted=true → 시스템 자동완료된 문의 제외
                if item.get("isCompleted") is True:
                    skipped += 1
                    continue
                
                print(f"    🟢 #{inq_no} | {item.get('userName', 'N/A')} | 주문: {item.get('orderNumber', 'N/A')}", flush=True)
                
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
            
            print(f"  [Parser] 결과: 未返信 {len(inquiries)}건 (完了 {skipped}건 제외)", flush=True)
            return inquiries
        except Exception as e:
            print(f"  ❌ [Parser] 실패: {e}", flush=True)
            return []

    async def get_item_details(self, item_url: str) -> Dict[str, Any]:
        """
        [v2.0] 라쿠텐 Item API를 통해 상품의 상세 설정(배리에이션 매핑 등)을 가져옵니다.
        """
        endpoint = "https://api.rms.rakuten.co.jp/es/2.0/item/getItem"
        params = {"itemUrl": item_url}
        
        try:
            client = await self._get_client()
            res = await client.get(endpoint, params=params)
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
            client = await self._get_client()
            res = await client.get(url)
            if res.status_code == 200:
                data = res.json()
                return data.get("variantList", [])
        except Exception as e:
            logger.error(f"🔥 [Rakuten Variant List] 예외 발생: {e}")
            
        return []

    async def get_inventory_external(self, manage_number: str, variant_id: str) -> int | None:
        """
        [v2.1] 라쿠텐 Inventory API를 통해 특정 SKU의 현재 가용 재고를 조회합니다.
        429(QPS 초과) 에러 발생 시 1초 대기 후 최대 1회 재시도합니다.
        """
        if not manage_number or not variant_id:
            return None

        manage_number = manage_number.lower()
        url = f"https://api.rms.rakuten.co.jp/es/2.1/inventories/manage-numbers/{manage_number}/variants/{variant_id}"
        
        client = await self._get_client()
        for attempt in range(2):
            try:
                res = await client.get(url)
                
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
