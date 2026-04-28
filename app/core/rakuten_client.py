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
    라쿠텐 RMS API (最新 InquiryManagementAPI) 와 통신하는 クライアントです.
    XML 대신 最新 JSON フォーマット을 使用하며 inquirymng-api エンドポイント를 呼び出しします.
    """
    def __init__(self, service_secret: str, license_key: str):
        auth_str = f"{service_secret}:{license_key}"
        encoded_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        self.headers = {
            "Authorization": f"ESA {encoded_auth}",
            "Content-Type": "application/json; charset=utf-8"
        }
        # 最新 Inquiry Management API エンドポイント
        self.base_url = "https://api.rms.rakuten.co.jp/es/1.0/inquirymng-api"
        # 공유 HTTP クライアント (TCP 接続 재使用で 성능 향상)
        self._shared_client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """공유 HTTP クライアント를 返却します. 없으면 새로 生成します."""
        if self._shared_client is None or self._shared_client.is_closed:
            self._shared_client = httpx.AsyncClient(timeout=15.0, headers=self.headers)
        return self._shared_client

    async def close(self):
        """공유 HTTP クライアント를 닫します."""
        if self._shared_client and not self._shared_client.is_closed:
            await self._shared_client.aclose()
            self._shared_client = None

    async def get_inquiry_list(self) -> List[Dict[str, Any]]:
        """
        라쿠텐 RMS로から 모든 ページ의 お問い合わせ リスト을 수집します. (비同期 Pagination)
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
                        print(f"  [API] レスポンス: totalPages={total_pages}, 現在 ページ お問い合わせ={raw_count}件", flush=True)
                        
                        inquiries = self._parse_json_inquiries(json_data)
                        all_inquiries.extend(inquiries)
                        
                        print(f"  [API] {current_page}ページ完了 (未返信 누계: {len(all_inquiries)}件)", flush=True)
                        current_page += 1
                        
                        await asyncio.sleep(0.1)
                    else:
                        print(f"  ❌ [API] HTTP {res.status_code}: {res.text[:200]}", flush=True)
                        break
                
                print(f"  [API] 수집 完了! 合計 未返信 {len(all_inquiries)}件", flush=True)
                return all_inquiries
        except Exception as e:
            print(f"  ❌ [API] 接続 失敗: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return []

    async def send_reply(self, inquiry_id: str, shop_id: str, reply_text: str) -> bool:
        """
        지정된 お問い合わせ에 返信을 発送します.
        공식 ドキュメント: POST https://api.rms.rakuten.co.jp/es/1.0/inquirymng-api/inquiry/reply
        """
        endpoint = f"{self.base_url}/inquiry/reply"
        payload = {
            "inquiryNumber": inquiry_id,
            "shopId": str(shop_id),
            "message": reply_text
        }
        
        try:
            logger.info(f"📤 [Rakuten API] 問い合わせID {inquiry_id} (Shop: {shop_id}) 에 返信送信 중...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(endpoint, headers=self.headers, json=payload)
                
                if res.status_code in [200, 201]:
                    logger.info(f"✅ [Rakuten API] 返信送信 成功: {inquiry_id}")
                    return True
                else:
                    logger.error(f"❌ [Rakuten API] 返信送信 失敗 ({res.status_code}): {res.text}")
                    return False
        except Exception as e:
            logger.error(f"❌ [Rakuten API] 発送 중 例外 발생: {e}")
            return False

    async def get_order_details(self, order_number: str) -> Dict[str, Any]:
        """
        注文番号를 기반で 라쿠텐 Order API v2.0で 注文 詳細 情報를 가져옵니다.
        URL: POST https://api.rms.rakuten.co.jp/es/2.0/order/getOrder
        """
        endpoint = "https://api.rms.rakuten.co.jp/es/2.0/order/getOrder"
        payload = {
            "orderNumberList": [order_number],
            "version": 7  # Rakuten API v2.0で 필수 요구하는 버전 情報
        }
        
        try:
            logger.info(f"📡 [Rakuten Order API] 注文番号 {order_number} 詳細 照会 試行...")
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(endpoint, headers=self.headers, json=payload)
                
                logger.info(f"📥 [Rakuten Order API] レスポンス コード: {res.status_code}")
                if res.status_code == 200:
                    data = res.json()
                    # 대소문자 구분 없이 찾기 試行
                    order_list = data.get("OrderModelList") or data.get("orderModelList") or []
                    if order_list:
                        return order_list[0]
                    else:
                        logger.warning(f"⚠️ [Rakuten Order API] 注文 データ를 찾을 수 ありません: {data}")
                        return {}
                else:
                    logger.error(f"❌ [Rakuten Order API] 照会 失敗: {res.text}")
                    return {}
        except Exception as e:
            logger.error(f"❌ [Rakuten Order API] 例外 발생: {e}")
            return {}

    def _parse_json_inquiries(self, json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        라쿠텐 API レスポンス을 パーシングします.
        UNICONA 未返信 = noMerchantReply(API) + isCompleted=false(パーサー)
        """
        inquiries = []
        skipped = 0
        try:
            inquiry_list = json_data.get("list", [])
            print(f"  [Parser] API レスポンス {len(inquiry_list)}件 (isCompleted フィルター 適用)", flush=True)
            
            for item in inquiry_list:
                inq_no = str(item.get("inquiryNumber", "UNKNOWN"))
                
                # isCompleted=true → システム 自動完了된 お問い合わせ 除外
                if item.get("isCompleted") is True:
                    skipped += 1
                    continue
                
                print(f"    🟢 #{inq_no} | {item.get('userName', 'N/A')} | 注文: {item.get('orderNumber', 'N/A')}", flush=True)
                
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
            
            print(f"  [Parser] 結果: 未返信 {len(inquiries)}件 (完了 {skipped}件 除外)", flush=True)
            return inquiries
        except Exception as e:
            print(f"  ❌ [Parser] 失敗: {e}", flush=True)
            return []

    async def get_item_details(self, item_url: str) -> Dict[str, Any]:
        """
        [v2.0] 라쿠텐 Item API를 を通じて 商品의 詳細 設定(배리에이션 マッピング 등)을 가져옵니다.
        """
        endpoint = "https://api.rms.rakuten.co.jp/es/2.0/item/getItem"
        params = {"itemUrl": item_url}
        
        try:
            client = await self._get_client()
            res = await client.get(endpoint, params=params)
            if res.status_code == 200:
                return res.json().get("itemModel", {})
        except Exception as e:
            logger.error(f"🔥 [Rakuten Item API] 例外 발생: {e}")
            
        return {}

    async def get_variant_list(self, manage_number: str) -> List[str]:
        """
        [v2.1] 특정 商品(manageNumber)에 속한 모든 SKU(variantId) リスト을 가져옵니다.
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
            logger.error(f"🔥 [Rakuten Variant List] 例外 발생: {e}")
            
        return []

    async def get_inventory_external(self, manage_number: str, variant_id: str) -> int | None:
        """
        [v2.1] 라쿠텐 Inventory API를 を通じて 특정 SKU의 現在 가용 在庫를 照会します.
        429(QPS 超過) エラーが発生しました 시 1초 待機 후 最大 1회 再試行します.
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
                    logger.info(f"📊 [Inventory Debug] レスポンス データ: {data}")
                    # v2.1 規格: inventoryCount フィールド 使用 (혹은 quantity 確認)
                    count = data.get("inventoryCount")
                    if count is None:
                        count = data.get("quantity") # 하위 호환성 체크
                    return count
                elif res.status_code == 429:
                    if attempt == 0:
                        logger.warning(f"⚠️ [Rakuten Inventory] QPS 超過 (429). 1초 후 再試行します... ({manage_number}/{variant_id})")
                        await asyncio.sleep(1)
                        continue
                    else:
                        logger.error(f"❌ [Rakuten Inventory] QPS 超過 지속: {res.text}")
                elif res.status_code == 404:
                    logger.warning(f"⚠️ [Rakuten Inventory v2.1] 존재하지 않는 SKU: {manage_number}/{variant_id}")
                    return None
                else:
                    logger.error(f"❌ [Rakuten Inventory v2.1] エラー: {res.status_code} {res.text}")
                    return None
            except Exception as e:
                logger.error(f"🔥 [Rakuten Inventory v2.1] 例外 발생: {e}")
                return None
        
        return None
