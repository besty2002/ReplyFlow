from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
from datetime import datetime
from pydantic import BaseModel
from typing import Dict, Any

from app.models.inquiries import InquiryCreate, InquiryUpdate, InternalNoteCreate
from app.api.dependencies import get_current_user_context, get_user_supabase_client
from app.core.ai_client import ai_client
import logging
from app.core.shop_api import ShopAPIAdapter
from typing import List

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/")
def create_manual_inquiry(
    inquiry: InquiryCreate,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
) -> Dict[str, Any]:
    """
    관리자 대시보드(테스트 UI)를 통해 수동으로 고객 문의를 수집(Mock)합니다.
    사용자의 JWT 토큰 분석을 통해 무조건 해당 회사의 company_id가 바인딩됩니다.
    """
    company_id = user_context["company_id"]
    
    # Supabase Insert 형식 생성
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
        # Row Level Security ポリシーにより、所属会社が強制的に確認されます。
        res = supabase_client.table("inquiries").insert(insert_data).execute()
        return {"status": "success", "message": "問い合わせ作成完了", "data": res.data[0] if res.data else None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"テスト問い合わせの登録に失敗しました。エラー: {str(e)}")

class DraftRequest(BaseModel):
    order_status: str | None = None
    stock_count: int | None = None
    item_name: str | None = None
    sub_code: str | None = None
    delivery_info: Dict[str, Any] | None = None

@router.post("/{inquiry_id}/draft")
async def generate_draft(
    inquiry_id: str,
    request: DraftRequest | None = None,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    들어온 문의에 대해 AI 초안을 생성하여 reply_drafts 테이블에 저장합니다.
    (실시간 재고 및 주문 상태 컨텍스트 반영)
    """
    company_id = user_context["company_id"]
    
    # 1. 문의 원본 내용 조회
    res = supabase_client.table("inquiries").select("*").eq("id", inquiry_id).eq("company_id", company_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")
    inquiry = res.data[0]
    
    # 2. 이미 존재하는 초안이 있는지 체크 -> 있다면 삭제하고 새로 생성 (재생성 허용)
    supabase_client.table("reply_drafts").delete().eq("inquiry_id", inquiry_id).execute()
        
    # 3. 실시간 컨텍스트 결합
    full_context = inquiry.copy()
    if request:
        full_context.update(request.dict(exclude_none=True))
    
    # 3.5. 회사 CS 가이드라인 로드
    try:
        comp_res = supabase_client.table("companies").select("cs_guidelines").eq("id", company_id).execute()
        if comp_res.data and comp_res.data[0].get("cs_guidelines"):
            full_context["cs_guidelines"] = comp_res.data[0]["cs_guidelines"]
    except Exception:
        pass  # 가이드라인 로드 실패 시 무시

    # 4. AI 초안 생성 및 카테고리 분류
    ai_result = await ai_client.generate_reply(
        inquiry_text=inquiry["content"],
        context=full_context
    )
    generated_text = ai_result.get("reply", "에러가 발생했습니다.")
    category = ai_result.get("category", "미분류")
    
    # 분류된 카테고리를 원본 고객 문의 데이터에 업데이트
    try:
        supabase_client.table("inquiries").update({
            "category": category
        }).eq("id", inquiry_id).execute()
    except Exception as e:
        print(f"카테고리 업데이트 무시 (DB 스키마 미적용 가능성): {e}")

    # 4. reply_drafts 테이블에 저장
    draft_data = {
        "company_id": company_id,
        "inquiry_id": inquiry_id,
        "ai_suggested_reply": generated_text,
        "status": "draft"
    }
    insert_res = supabase_client.table("reply_drafts").insert(draft_data).execute()
    return {"status": "success", "message": "초안 생성 완료", "data": insert_res.data[0]}

@router.post("/{inquiry_id}/analyze")
async def analyze_inquiry_metadata(
    inquiry_id: str,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    문의 내용의 감정, 태그, 카테고리를 AI로 재분석하여 업데이트합니다.
    """
    company_id = user_context["company_id"]
    
    # 1. 문의 내용 조회
    res = supabase_client.table("inquiries").select("content").eq("id", inquiry_id).eq("company_id", company_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")
    
    # 2. AI 분석 수행
    metadata = await ai_client.analyze_metadata(res.data[0]["content"])
    
    # 3. DB 업데이트
    update_data = {
        "category": metadata.get("category"),
        "sentiment": metadata.get("sentiment"),
        "sentiment_score": metadata.get("sentiment_score"),
        "ai_tags": metadata.get("tags"),
        "priority": metadata.get("priority_suggestion")
    }
    
    supabase_client.table("inquiries").update(update_data).eq("id", inquiry_id).execute()
    
    return {"status": "success", "data": update_data}

@router.get("/{inquiry_id}")
async def get_inquiry_detail(
    inquiry_id: str,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    문의 상세 정보와 관련 데이터(초안, 메모)를 한꺼번에 가져옵니다.
    """
    company_id = user_context["company_id"]
    
    # 문의 본체 + 숍 정보 + 초안 + 메모
    res = supabase_client.table("inquiries").select("*, connected_shops(*), reply_drafts(*), internal_notes(*)").eq("id", inquiry_id).eq("company_id", company_id).execute()
    
    if not res.data:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")
        
    return {"status": "success", "data": res.data[0]}

@router.post("/drafts/{draft_id}/approve")
async def approve_draft(
    draft_id: str,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    AI 초안 내용을 승인하고 최종 발송 처리(send_logs 기록, inquiries 상태 변경)를 수행합니다.
    """
    company_id = user_context["company_id"]
    user_id = user_context["user_id"]
    
    # 1. 초안 정보 가져오기
    res = supabase_client.table("reply_drafts").select("*").eq("id", draft_id).eq("company_id", company_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="초안을 찾을 수 없습니다.")
    draft = res.data[0]
    
    if draft["status"] == "approved":
        raise HTTPException(status_code=400, detail="이미 승인된 초안입니다.")
        
    inquiry_id = draft["inquiry_id"]
    
    # 원본 질문 조회를 위해 문의 내용 가져오기 (학습 데이터 기록용)
    inq_res = supabase_client.table("inquiries").select("*").eq("id", inquiry_id).execute()
    inquiry_text = inq_res.data[0]["content"] if inq_res.data else "내용 없음"
    
    # 2. 초안 승인 처리 (상태 변경)
    supabase_client.table("reply_drafts").update({
        "status": "approved",
        "approved_by": user_id,
        "approved_at": datetime.utcnow().isoformat()
    }).eq("id", draft_id).execute()
    
    # 3. 문의(Inquiry) 본체의 상태도 완료로 변경
    supabase_client.table("inquiries").update({
        "status": "replied"
    }).eq("id", inquiry_id).execute()
    
    # 4. 소속 숍의 API 정보 가져오기 및 실제 발송 시도
    logger_status = "success"
    shop_id = inq_res.data[0].get("shop_id")
    
    if shop_id:
        shop_res = supabase_client.table("connected_shops").select("*").eq("id", shop_id).execute()
        if shop_res.data:
            shop = shop_res.data[0]
            # 플랫폼별 API 어댑터 호출 (실제 외부 발송)
            send_res = await ShopAPIAdapter.send_reply(
                platform=shop["platform"],
                api_key=shop["api_key"],
                api_secret=shop.get("api_secret", ""),
                rakuten_inquiry_id=inq_res.data[0]["rakuten_inquiry_id"],
                reply_text=draft["ai_suggested_reply"],
                shop_id=shop.get("shop_name") # 라쿠텐의 경우 샵ID가 필요함 (여기선 shop_name에 저장되어있을 가능성 확인필요)
            )
            logger_status = send_res.get("status", "success")
        else:
            print(f"⚠️ [Approve] shop_id({shop_id})에 해당하는 숍을 찾을 수 없습니다. 로그만 남깁니다.")
    else:
        print("ℹ️ [Approve] shop_id가 없는 수동 테스트 데이터입니다. 외부 API 발송 없이 성공 처리합니다.")

    # 5. 발송 로그 생성
    supabase_client.table("send_logs").insert({
        "company_id": company_id,
        "inquiry_id": inquiry_id,
        "sent_reply": draft["ai_suggested_reply"],
        "sent_by": user_id,
        "status": logger_status
    }).execute()
    
    # 5. AI 학습용 데이터 로그(ai_training_logs) 생성
    inquiry_category = inq_res.data[0].get("category", "未分類") if inq_res.data else "未分類"
    
    supabase_client.table("ai_training_logs").insert({
        "company_id": company_id,
        "inquiry_id": inquiry_id,
        "question": inquiry_text,
        "category": inquiry_category,
        "final_answer": draft["ai_suggested_reply"],
        "approved_at": datetime.utcnow().isoformat()
    }).execute()
    
    return {"status": "success", "message": "承認および送信が正常に処理されました。"}

@router.post("/{inquiry_id}/send_reply")
async def send_inquiry_reply(
    inquiry_id: str,
    payload: Dict[str, str],
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    편집기에서 수정한 답변 내용을 실제로 발송합니다.
    """
    company_id = user_context["company_id"]
    user_id = user_context["user_id"]
    reply_text = payload.get("reply_text")
    
    if not reply_text:
        raise HTTPException(status_code=400, detail="답변 내용을 입력해주세요.")

    # 1. 문의 정보 및 연동된 샵 정보 가져오기
    inq_res = supabase_client.table("inquiries").select("*, connected_shops(*)").eq("id", inquiry_id).execute()
    if not inq_res.data:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")
    
    inquiry = inq_res.data[0]
    shop = inquiry.get("connected_shops")
    
    if not shop:
        raise HTTPException(status_code=400, detail="연결된 숍 정보를 찾을 수 없습니다.")

    # 2. 실제 외부 API 발송 (라쿠텐 등)
    send_res = await ShopAPIAdapter.send_reply(
        platform=shop["platform"],
        api_key=shop["api_key"],
        api_secret=shop.get("api_secret", ""),
        rakuten_inquiry_id=inquiry["rakuten_inquiry_id"],
        reply_text=reply_text,
        shop_id=shop.get("shop_name") # TODO: 실제 라쿠텐 샵 ID 필드 확인 필요
    )

    if send_res["status"] == "success":
        # 3. 성공 시 상태 업데이트
        supabase_client.table("inquiries").update({"status": "replied"}).eq("id", inquiry_id).execute()
        
        # 4. 발송 로그 및 AI 학습 로그 기록
        supabase_client.table("send_logs").insert({
            "company_id": company_id,
            "inquiry_id": inquiry_id,
            "sent_reply": reply_text,
            "sent_by": user_id,
            "status": "success"
        }).execute()
        
        return {"status": "success", "message": "답변이 성공적으로 전송되었습니다."}
@router.get("/{inquiry_id}/realtime_details")
async def get_realtime_details(
    inquiry_id: str,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    라쿠텐 API를 직접 호출하여 실시간 주문 상세 및 재고 현황을 가져옵니다.
    """
    try:
        # 1. DB에서 주문번호 및 숍 API 정보 가져오기
        logger.info(f"🔍 [Realtime Details] 조회 요청: {inquiry_id}")
        inq_res = supabase_client.table("inquiries").select("*, connected_shops(*)").eq("id", inquiry_id).execute()
        
        if not inq_res.data:
            logger.error(f"❌ [Realtime Details] 문의를 찾을 수 없음: {inquiry_id}")
            raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")
        
        inquiry = inq_res.data[0]
        order_number = inquiry.get("order_number")
        shop = inquiry.get("connected_shops")
        
        if not order_number:
            logger.warning(f"⚠️ [Realtime Details] 주문번호 없음: {inquiry_id}")
            return {"status": "no_order", "message": "주문번호가 없는 문의입니다."}
        
        if not shop:
            logger.error(f"❌ [Realtime Details] 연결된 숍 정보 없음: {inquiry_id}")
            raise HTTPException(status_code=400, detail="연결된 숍 정보가 없습니다.")

        # 2. 라쿠텐 클라이언트 초기화 및 조회
        from app.core.rakuten_client import RakutenRMSClient
        key_preview = f"{shop['api_key'][:5]}*** / {shop['api_secret'][:5]}***"
        # 터미널에서 확실히 보이도록 warning 레벨 사용
        logger.warning(f"🔑 [DEBUG AUTH] 상점: {shop.get('shop_name')} | 사용 중인 키: {key_preview}")
        rakuten = RakutenRMSClient(service_secret=shop["api_key"], license_key=shop["api_secret"])
        
        # 실시간 주문 정보 조회
        order_data = await rakuten.get_order_details(order_number)
        
        # 서브스테이터스 디버그 로그
        if order_data:
            print(f"  [Order] subStatusId={order_data.get('subStatusId')}, subStatusName={order_data.get('subStatusName')}, orderProgress={order_data.get('orderProgress')}", flush=True)
        else:
            logger.warning(f"⚠️ [Realtime Details] 라쿠텐 주문 조회 결과 없음: {order_number}")
            return {"status": "failed", "message": "라쿠텐에서 주문 정보를 찾을 수 없습니다."}

        # 3. 데이터 가공 및 반환
        items = []
        if order_data.get("PackageModelList"):
            for pkg in order_data["PackageModelList"]:
                for item in pkg.get("ItemModelList", []):
                    # SKU 정보 추출 (SkuModelList 우선 확인)
                    sku_list = item.get("SkuModelList", [])
                    raw_sku = ""
                    api_variant_id = "" # 실제 API 호출에 사용될 고유 ID (예: 18282)
                    
                    if sku_list:
                        # merchantDefinedSkuId (uc-0838■uc-0838_03)
                        raw_sku = sku_list[0].get("merchantDefinedSkuId") or ""
                        # variantId (18282)
                        api_variant_id = sku_list[0].get("variantId") or ""
                    
                    if not raw_sku:
                        # Fallback: 기존 후보 필드들 확인
                        raw_sku = str(item.get("skuCode") or item.get("manageNumber") or item.get("itemNumber") or "").strip()
                        api_variant_id = raw_sku

                    # 라쿠텐 v2.1 규격에 맞게 manageNumber와 display용 서브코드 분리
                    if "■" in raw_sku:
                        sku_parts = raw_sku.split("■")
                        manage_number = sku_parts[0]
                        display_sub_code = sku_parts[-1]
                    else:
                        manage_number = item.get("manageNumber") or item.get("itemNumber") or raw_sku
                        display_sub_code = raw_sku
                    
                    # [보완] 만약 api_variant_id가 manage_number와 같고(배리에이션 미특정), 선택 옵션이 있다면 상품 정보에서 매핑 시도
                    choices = (item.get("selectedChoice") or "").strip()
                    if api_variant_id == manage_number and choices:
                        logger.info(f"🔍 [SKU Mapping] 배리에이션 매핑 시도: {manage_number} / {choices}")
                        item_details = await rakuten.get_item_details(manage_number)
                        variants = item_details.get("variantModelList", [])
                        for v in variants:
                            v_values = " ".join([vv.get("variationValue", "") for vv in v.get("variationValues", [])])
                            if choices in v_values or v_values in choices:
                                logger.info(f"✅ [SKU Mapping] 매칭 성공: {v.get('variantId')}")
                                api_variant_id = v.get("variantId")
                                # 화면 표시용 서브코드도 가능하다면 업데이트
                                display_sub_code = v.get("merchantDefinedSkuId") or v.get("variantId")
                                if "■" in display_sub_code:
                                    display_sub_code = display_sub_code.split("■")[-1]
                                break

                    # 실시간 재고 조회 (api_variant_id 사용)
                    logger.warning(f"📡 [Inventory Request] 상품코드: {manage_number} | SKU ID: {api_variant_id}")
                    stock_count = await rakuten.get_inventory_external(manage_number, api_variant_id)
                        
                    choices = (item.get("selectedChoice") or "").strip()
                    # 만약 raw_sku에 선택사항 정보가 없고 choices에 있다면 합침
                    if choices and choices not in raw_sku:
                        full_display_code = f"{display_sub_code} ({choices})".strip()
                    else:
                        full_display_code = display_sub_code or "-"
                    
                    # お届け目安 判定
                    delivery_estimate = "当日出荷" if (stock_count is not None and stock_count > 0) else "7-10日営業日発送"
                    
                    items.append({
                        "itemName": item.get("itemName"),
                        "itemNumber": item.get("itemNumber"),
                        "skuCode": full_display_code,
                        "units": item.get("units"),
                        "stockCount": stock_count,
                        "deliveryEstimate": delivery_estimate,
                    })

        # 4. 発送判定 (全SKUの在庫を確認)
        out_of_stock_skus = []
        for itm in items:
            if itm.get("stockCount") is None or itm["stockCount"] <= 0:
                out_of_stock_skus.append(f"{itm.get('itemNumber', '?')}/{itm.get('skuCode', '?')}")
        
        all_shippable = len(out_of_stock_skus) == 0 and len(items) > 0
        shipping_verdict = {
            "canShip": all_shippable,
            "status": "発送可能" if all_shippable else "発送不可",
            "reason": "全SKU在庫あり" if all_shippable else f"在庫切れ: {', '.join(out_of_stock_skus)}",
            "details": [
                {"sku": itm.get("skuCode"), "stock": itm.get("stockCount"), "estimate": itm.get("deliveryEstimate")}
                for itm in items
            ]
        }
        print(f"  [発送判定] {shipping_verdict['status']} ({shipping_verdict['reason']})", flush=True)

        # 5. 배송 정보 추출 (라쿠텐 주문 데이터에서 직접)
        delivery_info = None
        order_progress = str(order_data.get("orderProgress", ""))
        
        # 配送会社ID → 名前マッピング
        company_map = {
            "1001": "ヤマト運輸", "1002": "佐川急便", "1003": "日本郵便",
            "1004": "西濃運輸", "1005": "セイノースーパーエクスプレス",
            "1006": "福山通運", "1007": "名鉄運輸", "1008": "トナミ運輸",
            "1009": "第一貨物", "1010": "新潟運輸", "1011": "中越運送",
            "1012": "岡山県貨物", "1013": "久留米運送", "1014": "山陽自動車運送",
            "1015": "NXトランスポート", "1016": "エコ配", "1017": "EMS",
            "1018": "DHL", "1019": "FedEx", "1020": "UPS",
            "1021": "日本通運", "1022": "TNT", "1023": "OCS",
            "1024": "USPS", "1025": "SFエクスプレス", 
            "1026": "Aramex", "1027": "SGHグローバル・ジャパン",
        }
        
        # PackageModelList → ShippingModelList에서 전표번호 추출
        try:
            # 注文レベルの備考からお届け日を抽出（例: [配送日時指定] 2026-04-28(火)）
            order_delivery_date = None
            remarks = order_data.get("remarks") or order_data.get("memo") or ""
            if not remarks:
                # deliveryDate が注文トップレベルにある可能性
                order_delivery_date = order_data.get("deliveryDate") or order_data.get("arrivalDate")
            else:
                import re
                date_match = re.search(r'配送日[時指定]*[】\]]\s*(\d{4}-\d{2}-\d{2})', str(remarks))
                if date_match:
                    order_delivery_date = date_match.group(1)
            
            packages = order_data.get("PackageModelList") or []
            for pkg in packages:
                shipping_list = pkg.get("ShippingModelList") or []
                for ship in shipping_list:
                    tracking = ship.get("shippingNumber")
                    # API応答の実フィールド: deliveryCompanyName = "ヤマト運輸"
                    company_name = ship.get("deliveryCompanyName") or ship.get("deliveryCompany") or "-"
                    
                    if tracking:
                        delivery_info = {
                            "status": "success",
                            "tracking_number": str(tracking),
                            "shipping_company": company_name,
                            "shipping_date": ship.get("shippingDate"),
                            "delivery_date": order_delivery_date,
                        }
                        print(f"  [配送] 伝票={tracking}, 会社={company_name}, 発送={ship.get('shippingDate')}, 届け={order_delivery_date}", flush=True)
                        break
                if delivery_info:
                    break
        except Exception as e:
            print(f"  ⚠️ [配送] 情報抽出エラー: {e}", flush=True)

        return {
            "status": "success",
            "order_info": {
                "order_number": order_data.get("orderNumber"),
                "order_status": order_data.get("orderProgress"),
                "sub_status_id": order_data.get("subStatusId"),
                "sub_status_name": order_data.get("subStatusName"),
                "order_date": order_data.get("orderDatetime"),
                "total_price": order_data.get("totalPrice")
            },
            "items": items,
            "shipping_verdict": shipping_verdict,
            "delivery_info": delivery_info
        }
    except Exception as e:
        logger.exception(f"🔥 [Realtime Details] 처리 중 치명적 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{inquiry_id}")
async def update_inquiry(
    inquiry_id: str,
    update_data: InquiryUpdate,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    문의 상태, 담당자, 우선순위 등을 업데이트합니다.
    """
    company_id = user_context["company_id"]
    
    # exclude_unset=True를 사용하여 제공된 필드만 업데이트
    data = update_data.dict(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="업데이트할 데이터가 없습니다.")
        
    try:
        res = supabase_client.table("inquiries").update(data).eq("id", inquiry_id).eq("company_id", company_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")
        return {"status": "success", "data": res.data[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{inquiry_id}/notes")
async def get_internal_notes(
    inquiry_id: str,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    해당 문의의 내부 메모 목록을 가져옵니다.
    """
    company_id = user_context["company_id"]
    
    try:
        res = supabase_client.table("internal_notes").select("*").eq("inquiry_id", inquiry_id).eq("company_id", company_id).order("created_at", desc=False).execute()
        return {"status": "success", "data": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{inquiry_id}/notes")
async def create_internal_note(
    inquiry_id: str,
    note: InternalNoteCreate,
    user_context: dict = Depends(get_current_user_context),
    supabase_client: Client = Depends(get_user_supabase_client)
):
    """
    내부 메모를 작성합니다.
    """
    company_id = user_context["company_id"]
    user_id = user_context["user_id"]
    
    insert_data = {
        "inquiry_id": inquiry_id,
        "company_id": company_id,
        "author_id": user_id,
        "content": note.content,
        "created_at": datetime.utcnow().isoformat()
    }
    
    try:
        res = supabase_client.table("internal_notes").insert(insert_data).execute()
        return {"status": "success", "data": res.data[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
