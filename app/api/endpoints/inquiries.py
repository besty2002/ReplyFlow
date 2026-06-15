from fastapi import APIRouter, Depends, HTTPException, Response
from supabase import Client
import asyncio
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import logging

from app.models.inquiries import InquiryCreate, InquiryUpdate, InternalNoteCreate
from app.api.dependencies import get_current_user_context, get_user_supabase_client
from app.core.ai_client import ai_client
from app.core.shop_api import ShopAPIAdapter
from app.services.thread_context import fetch_and_format_inquiry_thread

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/")
def create_manual_inquiry(
    inquiry: InquiryCreate,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
) -> Dict[str, Any]:
    company_id = user_context["company_id"]
    insert_data = {
        "company_id": company_id,
        "rakuten_inquiry_id": f"TEST-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "customer_id": inquiry.customer_id,
        "title": inquiry.title,
        "content": inquiry.content,
        "received_at": datetime.utcnow().isoformat(),
        "status": "pending"
    }
    try:
        res = supabase_client.table("inquiries").insert(insert_data).execute()
        return {"status": "success", "message": "問い合わせ作成 완료", "data": res.data[0] if res.data else None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"등록 실패: {str(e)}")

class DraftRequest(BaseModel):
    order_status: str | None = None
    stock_count: int | None = None
    item_name: str | None = None
    sub_code: str | None = None
    items: List[Dict[str, Any]] | None = None
    shipping_verdict: str | None = None
    shipping_reason: str | None = None
    delivery_info: Dict[str, Any] | None = None

class SyncNowRequest(BaseModel):
    reason: str | None = "manual"


def _parse_sync_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

@router.get("/attachment")
async def get_attachment_proxy(
    path: str,
    token: str | None = None,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    # path에 | 가 포함되어 있으면 path, label, inquiry_id로 분리
    actual_path = path
    actual_label = "image.jpg"
    actual_inq_id = None
    
    parts = path.split("|")
    if len(parts) >= 2:
        actual_path = parts[0]
        actual_label = parts[1]
    if len(parts) >= 3:
        actual_inq_id = parts[2]
    
    # inquiryNumber로부터 shopId(상점번호) 추출 (예: 360077-20260507-59958557o -> 360077)
    extracted_shop_id = None
    if actual_inq_id and "-" in actual_inq_id:
        extracted_shop_id = actual_inq_id.split("-")[0]
    
    # 해당 상점 정보를 찾음
    shop_query = supabase_client.table("connected_shops").select("*").eq("company_id", user_context["company_id"]).eq("platform", "rakuten")
    if extracted_shop_id:
        # api_key에 상점번호가 포함되어 있는 상점을 찾음 (예: SP360077_...)
        shop_query = shop_query.ilike("api_key", f"%{extracted_shop_id}%")
    
    res = shop_query.limit(1).execute()
    if not res.data:
        # 만약 특정 상점을 못 찾으면 기본 상점이라도 사용
        res = supabase_client.table("connected_shops").select("*").eq("company_id", user_context["company_id"]).eq("platform", "rakuten").limit(1).execute()
        if not res.data:
            raise HTTPException(status_code=400, detail="Rakuten shop not connected")
    
    shop = res.data[0]
    from app.core.rakuten_client import RakutenRMSClient
    rakuten = RakutenRMSClient(service_secret=shop["api_key"], license_key=shop["api_secret"])
    
    logger.info(f"  [Proxy] Fetching attachment: path={actual_path}, label={actual_label}, inquiryNumber={actual_inq_id}, shopId={extracted_shop_id}")
    content = await rakuten.get_attachment(actual_path, actual_label, actual_inq_id, extracted_shop_id)
    if not content:
        logger.error(f"  [Proxy] Failed to fetch content from Rakuten: {actual_path}")
        raise HTTPException(status_code=404, detail="Attachment data not found or access denied")
        
    media_type = "image/jpeg"
    lower_label = actual_label.lower()
    if lower_label.endswith(".png"): media_type = "image/png"
    elif lower_label.endswith(".gif"): media_type = "image/gif"
    elif lower_label.endswith(".pdf"): media_type = "application/pdf"
    
    return Response(content=content, media_type=media_type)

@router.post("/sync-now")
async def sync_now(
    request: SyncNowRequest | None = None,
    user_context: dict = Depends(get_current_user_context),
):
    """
    ログイン済みユーザー向けの軽量な同期トリガーです。
    実際の同期はバックグラウンドで開始し、画面表示は待たせません。
    """
    from app.workers.sync_bot import _get_admin_supabase_client, reconcile_all_shops

    reason = (request.reason if request else "manual") or "manual"
    now = datetime.now(timezone.utc)
    supabase = _get_admin_supabase_client()
    status_res = supabase.table("sync_status").select("*").eq("sync_key", "rakuten_reconcile").limit(1).execute()
    sync_status = status_res.data[0] if status_res.data else {}

    last_started = _parse_sync_datetime(sync_status.get("last_started_at"))
    last_completed = _parse_sync_datetime(sync_status.get("last_completed_at"))
    last_touch = last_started or last_completed

    if sync_status.get("status") == "running" and last_started and now - last_started < timedelta(minutes=15):
        return {
            "status": "already_running",
            "message": "同期は既に実行中です。",
            "sync_status": sync_status,
        }

    if reason == "dashboard_load" and last_touch and now - last_touch < timedelta(minutes=3):
        return {
            "status": "skipped_recent",
            "message": "直近で同期済みのためスキップしました。",
            "sync_status": sync_status,
        }

    logger.info("[Sync Now] user=%s role=%s reason=%s", user_context.get("user_id"), user_context.get("role"), reason)
    asyncio.create_task(reconcile_all_shops())
    return {
        "status": "accepted",
        "message": "同期を開始しました。",
        "sync_status": sync_status,
    }

@router.get("/{inquiry_id}")
async def get_inquiry_detail(
    inquiry_id: str,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """상세 정보 조회"""
    res = supabase_client.table("inquiries").select("*, connected_shops(*), reply_drafts(*), internal_notes(*)").eq("id", inquiry_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="お問い合わせが見つかりません。")
    return {"status": "success", "data": res.data[0]}

@router.get("/{inquiry_id}/messages")
async def get_inquiry_messages(
    inquiry_id: str,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """메시지 내역 조회"""
    res = supabase_client.table("inquiries").select("*, connected_shops(*)").eq("id", inquiry_id).execute()
    if not res.data: raise HTTPException(status_code=404, detail="Not found")
    inquiry = res.data[0]
    shop = inquiry.get("connected_shops")
    
    if shop and shop.get("platform") == "rakuten":
        from app.core.rakuten_client import RakutenRMSClient
        rakuten = RakutenRMSClient(service_secret=shop["api_key"], license_key=shop["api_secret"])
        messages = await rakuten.get_inquiry_thread(inquiry["rakuten_inquiry_id"])
        return {"status": "success", "data": messages or []}
    
    return {"status": "success", "data": []}

@router.post("/{inquiry_id}/draft")
async def generate_draft(
    inquiry_id: str,
    request: DraftRequest | None = None,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    company_id = user_context["company_id"]
    res = supabase_client.table("inquiries").select("*, connected_shops(*)").eq("id", inquiry_id).execute()
    if not res.data: raise HTTPException(status_code=404, detail="Not found")
    inquiry = res.data[0]

    context = dict(inquiry)
    if request:
        context.update(request.dict(exclude_none=True))
    context["inquiry_thread"] = await fetch_and_format_inquiry_thread(inquiry)

    ai_result = await ai_client.generate_reply(inquiry_text=inquiry["content"], context=context)
    draft_data = {
        "company_id": company_id,
        "inquiry_id": inquiry_id,
        "ai_suggested_reply": ai_result.get("reply", ""),
        "status": "draft"
    }
    supabase_client.table("reply_drafts").delete().eq("inquiry_id", inquiry_id).execute()
    insert_res = supabase_client.table("reply_drafts").insert(draft_data).execute()
    return {"status": "success", "data": insert_res.data[0]}

@router.post("/{inquiry_id}/send_reply")
async def send_inquiry_reply(
    inquiry_id: str,
    payload: Dict[str, str],
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    reply_text = payload.get("reply_text")
    inq_res = supabase_client.table("inquiries").select("*, connected_shops(*)").eq("id", inquiry_id).execute()
    inquiry = inq_res.data[0]
    shop = inquiry.get("connected_shops")
    
    await ShopAPIAdapter.send_reply(
        platform=shop["platform"],
        api_key=shop["api_key"],
        api_secret=shop.get("api_secret", ""),
        rakuten_inquiry_id=inquiry["rakuten_inquiry_id"],
        reply_text=reply_text,
        shop_id=shop.get("shop_name")
    )
    supabase_client.table("inquiries").update({"status": "replied"}).eq("id", inquiry_id).execute()
    return {"status": "success"}

@router.get("/{inquiry_id}/realtime_details")
async def get_realtime_details(
    inquiry_id: str,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    inq_res = supabase_client.table("inquiries").select("*, connected_shops(*)").eq("id", inquiry_id).execute()
    if not inq_res.data:
        raise HTTPException(status_code=404, detail="Inquiry not found")
        
    inquiry = inq_res.data[0]
    order_number = inquiry.get("order_number")
    shop = inquiry.get("connected_shops")
    
    if not order_number or not shop:
        return {"status": "success", "order_info": {}, "items": [], "delivery_info": {"status": "none"}}
    
    from app.core.rakuten_client import RakutenRMSClient
    rakuten = RakutenRMSClient(service_secret=shop["api_key"], license_key=shop["api_secret"])
    order_data = await rakuten.get_order_details(order_number)
    
    # Rakuten v2.0 구조에 따른 데이터 가공
    # 실제 API 응답 확인 결과 orderStatus 대신 orderProgress가 사용될 수 있음
    order_status = order_data.get("orderStatus") or order_data.get("orderProgress")
    
    normalized_data = {
        "status": "success",
        "order_info": {
            "order_status": order_status
        },
        "items": [],
        "delivery_info": {"status": "none"}
    }
    
    if order_data:
        # 상품 리스트 추출
        packages = order_data.get("PackageModelList", [])
        if packages:
            first_pkg = packages[0]
            items_raw = first_pkg.get("ItemModelList", [])
            items_processed = []
            for item in items_raw:
                manage_number = item.get("manageNumber")
                variant_id = None
                merchant_sku_id = None
                sku_list = item.get("SkuModelList", [])
                if sku_list:
                    variant_id = sku_list[0].get("variantId")
                    merchant_sku_id = sku_list[0].get("merchantDefinedSkuId")
                
                # 실시간 재고 조회 (API 호출)
                current_stock = None
                if manage_number and variant_id:
                    try:
                        current_stock = await rakuten.get_inventory_external(manage_number, variant_id)
                    except: pass
                
                items_processed.append({
                    "itemName": item.get("itemName"),
                    "itemNumber": item.get("itemNumber"),
                    "skuCode": item.get("skuCode"),
                    "subCode": merchant_sku_id, # 서브코드 (merchantDefinedSkuId)
                    "quantity": item.get("units"), # 주문 수량
                    "stockCount": current_stock # 실시간 현재 재고
                })
            normalized_data["items"] = items_processed
            
            # 배송 정보 추출 (v2.0에서는 ShippingModelList 복수형일 수 있음)
            shipping_list = first_pkg.get("ShippingModelList", [])
            shipping = None
            if shipping_list:
                shipping = shipping_list[0]
            else:
                shipping = first_pkg.get("ShippingModel")
                
            if shipping:
                normalized_data["delivery_info"] = {
                    "status": "success",
                    "tracking_number": shipping.get("shippingNumber"),
                    "shipping_date": shipping.get("shippingDate")
                }
                
    return normalized_data

@router.patch("/{inquiry_id}")
async def update_inquiry(inquiry_id: str, update_data: InquiryUpdate, user_context: dict = Depends(get_current_user_context), supabase_client: Client = Depends(get_user_supabase_client)):
    res = supabase_client.table("inquiries").update(update_data.dict(exclude_unset=True)).eq("id", inquiry_id).execute()
    return {"status": "success", "data": res.data[0]}

@router.get("/{inquiry_id}/notes")
async def get_internal_notes(inquiry_id: str, user_context: dict = Depends(get_current_user_context), supabase_client: Client = Depends(get_user_supabase_client)):
    res = supabase_client.table("internal_notes").select("*").eq("inquiry_id", inquiry_id).execute()
    return {"status": "success", "data": res.data}

@router.post("/{inquiry_id}/notes")
async def create_internal_note(inquiry_id: str, note: InternalNoteCreate, user_context: dict = Depends(get_current_user_context), supabase_client: Client = Depends(get_user_supabase_client)):
    insert_data = {"inquiry_id": inquiry_id, "company_id": user_context["company_id"], "author_id": user_context["user_id"], "content": note.content}
    res = supabase_client.table("internal_notes").insert(insert_data).execute()
    return {"status": "success", "data": res.data[0]}
