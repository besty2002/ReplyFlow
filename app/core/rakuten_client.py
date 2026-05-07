from __future__ import annotations
import httpx
import asyncio
import logging
import base64
import uuid
import datetime
import re
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class RakutenRMSClient:
    """
    라쿠텐 RMS API (Inquiry Management API) 와 통신하는 클라이언트입니다.
    공식 지침(v2.0)에 따라 데이터 구조를 처리합니다.
    """
    def __init__(self, service_secret: str, license_key: str):
        auth_str = f"{service_secret}:{license_key}"
        encoded_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        self.headers = {
            "Authorization": f"ESA {encoded_auth}",
            "Content-Type": "application/json; charset=utf-8"
        }
        self.base_url = "https://api.rms.rakuten.co.jp/es/1.0/inquirymng-api"
        self._shared_client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._shared_client is None or self._shared_client.is_closed:
            self._shared_client = httpx.AsyncClient(timeout=15.0, headers=self.headers)
        return self._shared_client

    async def close(self):
        if self._shared_client and not self._shared_client.is_closed:
            await self._shared_client.aclose()
            self._shared_client = None

    async def get_inquiry_list(self) -> List[Dict[str, Any]]:
        """라쿠텐 RMS로부터 미返信 문의 목록을 수집합니다."""
        endpoint = f"{self.base_url}/inquiries"
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
                        "noMerchantReply": "true",
                    }
                    res = await client.get(endpoint, headers=self.headers, params=params)
                    if res.status_code == 200:
                        json_data = res.json()
                        total_pages = json_data.get("totalPageCount", 1)
                        inquiries = self._parse_json_inquiries(json_data)
                        all_inquiries.extend(inquiries)
                        current_page += 1
                        await asyncio.sleep(0.1)
                    else:
                        break
                return all_inquiries
        except Exception as e:
            logger.error(f"[API] Error fetching list: {e}")
            return []

    async def get_inquiry_thread(self, inquiry_id: str) -> List[Dict[str, Any]]:
        """라쿠텐 공식 지침에 따라 상세 대화 내역을 가져오고 정규화합니다."""
        endpoint = f"{self.base_url}/inquiry/{inquiry_id}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(endpoint, headers=self.headers)
                if res.status_code == 200:
                    json_data = res.json()
                    # 무조건 로그에 남도록 logger.warning 사용
                    logger.warning(f"  [RAW_RAKUTEN] inquiry_id={inquiry_id} | Data: {json_data}")
                    raw_messages = self._extract_messages_from_response(json_data)
                    return self._normalize_messages(raw_messages, inquiry_id)
                else:
                    return []
        except Exception as e:
            logger.error(f"[Thread] Exception: {e}")
            return []

    async def get_attachment(self, path: str, label: str = "image.jpg", inquiry_number: str | None = None, shop_id: str | None = None) -> bytes | None:
        """라쿠텐 API를 통해 첨부파일(이미지 등) 바이너리 데이터를 가져옵니다."""
        clean_path = path.lstrip("/")
        # 공식 엔드포인트는 /inquiry/attachment 이며, inquiryNumber와 shopId가 필수 파라미터일 수 있음
        endpoint = f"{self.base_url}/inquiry/attachment"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                params = {"path": clean_path, "label": label}
                if inquiry_number:
                    params["inquiryNumber"] = inquiry_number
                if shop_id:
                    params["shopId"] = shop_id
                
                logger.info(f"[Attachment] Requesting URL: {endpoint} | params={params}")
                
                headers = self.headers.copy()
                if "Content-Type" in headers:
                    del headers["Content-Type"]
                
                res = await client.get(endpoint, headers=headers, params=params)
                if res.status_code == 200:
                    return res.content
                else:
                    logger.error(f"[Attachment] API Error {res.status_code}: {res.text} | URL: {res.url}")
                    # 만약 400(IE001 - inquiryNumber/shopId 누락 등)이나 403, 404가 나면 기존 경로로도 시도
                    if res.status_code in [400, 403, 404]:
                        old_endpoint = f"{self.base_url}/attachment"
                        logger.info(f"[Attachment] Retrying with old endpoint: {old_endpoint}")
                        res2 = await client.get(old_endpoint, headers=headers, params={"path": clean_path, "label": label})
                        if res2.status_code == 200:
                            return res2.content
                        logger.error(f"[Attachment] Fallback failed: {res2.status_code}")
                    return None
        except Exception as e:
            logger.error(f"[Attachment] Exception: {e}")
            return None

    def _extract_messages_from_response(self, json_data: dict) -> list:
        """공식 지침: result.message(최초) + result.replies(추가) 통합 추출"""
        res = json_data.get("result")
        if not res or not isinstance(res, dict): return []
        all_msgs = []
        first_msg = {
            "message": res.get("message"),
            "regDate": res.get("regDate"),
            "replyFrom": "user",
            "attachments": res.get("attachments") or []
        }
        if first_msg["message"]: all_msgs.append(first_msg)
        replies = res.get("replies") or []
        if isinstance(replies, list): all_msgs.extend(replies)
        return all_msgs

    def _normalize_messages(self, message_list: list, inquiry_id: str | None = None) -> list:
        """공식 지침의 replyFrom 필드와 regDate 규격을 사용하여 정규화 및 정렬합니다."""
        def parse_date(date_str):
            if not date_str: return None
            try:
                nums = re.sub(r'[^0-9]', '', str(date_str))
                if len(nums) >= 14: return datetime.datetime.strptime(nums[:14], "%Y%m%d%H%M%S")
                return None
            except: return None

        normalized = []
        for i, msg in enumerate(message_list):
            content = msg.get("message") or ""
            reply_from = msg.get("replyFrom")
            sender = "2" if reply_from == "merchant" else "1"
            raw_date = msg.get("regDate") or ""
            parsed_dt = parse_date(raw_date)
            
            images = []
            attachments = msg.get("attachments") or []
            if isinstance(attachments, list):
                for att in attachments:
                    # 상세 로깅
                    logger.warning(f"  [ATT_DEBUG] Raw attachment: {att}")
                    path = att.get("path")
                    # 다양한 키 후보군 확인
                    label = att.get("label") or att.get("fileName") or att.get("name") or att.get("attachmentLabel") or "image.jpg"
                    if path:
                        # 이미지를 프록시할 때 inquiry_id가 필요할 수 있으므로 포함
                        if inquiry_id:
                            images.append(f"{path}|{label}|{inquiry_id}")
                        else:
                            images.append(f"{path}|{label}")
            
            normalized.append({
                "message": content, "senderType": sender, "createdDateTime": raw_date,
                "parsed_dt": parsed_dt or datetime.datetime.min, "images": images, "orig_idx": i
            })
        normalized.sort(key=lambda x: (x["parsed_dt"], x["orig_idx"]))
        for n in normalized:
            del n["parsed_dt"]
            del n["orig_idx"]
        return normalized

    async def send_reply(self, inquiry_id: str, shop_id: str, reply_text: str) -> bool:
        endpoint = f"{self.base_url}/inquiry/reply"
        payload = {"inquiryNumber": inquiry_id, "shopId": str(shop_id), "message": reply_text}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(endpoint, headers=self.headers, json=payload)
                return res.status_code in [200, 201]
        except: return False

    async def get_order_details(self, order_number: str) -> Dict[str, Any]:
        endpoint = "https://api.rms.rakuten.co.jp/es/2.0/order/getOrder"
        payload = {"orderNumberList": [order_number], "version": 7}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(endpoint, headers=self.headers, json=payload)
                if res.status_code == 200:
                    json_data = res.json()
                    logger.info(f"[RakutenAPI] getOrder result: {json_data}")
                    order_list = json_data.get("OrderModelList", [])
                    if not order_list:
                        logger.warning(f"[RakutenAPI] No order found for {order_number}. Messages: {json_data.get('MessageModelList')}")
                    return order_list[0] if order_list else {}
                else:
                    logger.error(f"[RakutenAPI] getOrder failed with {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"[RakutenAPI] getOrder exception: {e}")
        return {}

    def _parse_json_inquiries(self, json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        inquiries = []
        for item in json_data.get("list", []):
            if item.get("isCompleted") is True: continue
            inquiries.append({
                "rakuten_inquiry_id": str(item.get("inquiryNumber")),
                "customer_id": item.get("userName", "Anonymous"),
                "title": "楽天 顧客問い合わせ",
                "content": item.get("message", ""),
                "received_at": item.get("regDate", ""),
                "order_number": item.get("orderNumber"),
                "item_name": item.get("itemName"),
                "item_number": item.get("itemNumber"),
                "category": item.get("category"),
                "type": item.get("type")
            })
        return inquiries

    async def get_item_details(self, item_url: str) -> Dict[str, Any]:
        endpoint = "https://api.rms.rakuten.co.jp/es/2.0/item/getItem"
        try:
            client = await self._get_client()
            res = await client.get(endpoint, params={"itemUrl": item_url})
            if res.status_code == 200: return res.json().get("itemModel", {})
        except: pass
        return {}

    async def get_variant_list(self, manage_number: str) -> List[str]:
        if not manage_number: return []
        url = f"https://api.rms.rakuten.co.jp/es/2.1/inventories/variant-lists/manage-numbers/{manage_number.lower()}"
        try:
            client = await self._get_client()
            res = await client.get(url)
            if res.status_code == 200: return res.json().get("variantList", [])
        except: pass
        return []

    async def get_inventory_external(self, manage_number: str, variant_id: str) -> int | None:
        if not manage_number or not variant_id: return None
        url = f"https://api.rms.rakuten.co.jp/es/2.1/inventories/manage-numbers/{manage_number.lower()}/variants/{variant_id}"
        client = await self._get_client()
        try:
            res = await client.get(url)
            if res.status_code == 200:
                data = res.json()
                return data.get("inventoryCount") or data.get("quantity")
        except: pass
        return None
