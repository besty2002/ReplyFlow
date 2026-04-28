import asyncio
import os
import logging
import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from supabase import create_client, Client
from app.core.config import settings
from app.core.rakuten_client import RakutenRMSClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# 스케줄러 전역 인스턴스
scheduler = AsyncIOScheduler()


async def reconcile_shop_inquiries(shop: dict, supabase: Client) -> dict:
    """
    단일 숍의 RMS 未返信 목록과 DB를 대조하여 동기화합니다.
    - RMS에만 있는 문의 → INSERT (신규)
    - DB에만 있는 문의 → DELETE (RMS에서 완료/답변됨)
    - 양쪽 모두 있는 문의 → 유지
    """
    platform = shop["platform"]
    shop_name = shop["shop_name"]
    shop_id = shop.get("id")
    company_id = shop.get("company_id")

    result = {"shop": shop_name, "inserted": 0, "deleted": 0, "unchanged": 0, "errors": []}

    # 1. RMS에서 현재 未返信 목록 수집
    rms_inquiries = []
    if platform == "rakuten":
        rakuten = RakutenRMSClient(
            service_secret=shop.get("api_key", ""),
            license_key=shop.get("api_secret", "")
        )
        rms_inquiries = await rakuten.get_inquiry_list()

    rms_map = {inq["rakuten_inquiry_id"]: inq for inq in rms_inquiries}
    rms_ids = set(rms_map.keys())
    print(f"  [RMS] {shop_name}: 未返信 {len(rms_ids)}건 수신", flush=True)

    # 2. DB에서 현재 해당 숍의 문의 목록 조회
    db_res = supabase.table("inquiries") \
        .select("id, rakuten_inquiry_id") \
        .eq("shop_id", shop_id) \
        .execute()
    db_data = db_res.data or []
    db_map = {row["rakuten_inquiry_id"]: row["id"] for row in db_data if row.get("rakuten_inquiry_id")}
    db_ids = set(db_map.keys())
    print(f"  [DB]  {shop_name}: 기존 {len(db_ids)}건 보유", flush=True)

    # 3. 대조 비교
    to_insert = rms_ids - db_ids    # RMS에만 있음 → 신규
    to_delete = db_ids - rms_ids    # DB에만 있음 → RMS에서 완료됨
    unchanged = rms_ids & db_ids    # 양쪽 모두 → 유지

    print(f"  [대조] 신규={len(to_insert)}건, 삭제={len(to_delete)}건, 유지={len(unchanged)}건", flush=True)

    # 4. 신규 문의 INSERT
    for rakuten_id in to_insert:
        ext_inq = rms_map[rakuten_id]
        try:
            new_data = {
                "company_id": company_id,
                "shop_id": shop_id,
                "rakuten_inquiry_id": rakuten_id,
                "customer_id": ext_inq.get("customer_id", "Unknown"),
                "title": ext_inq.get("title", "No Title"),
                "content": ext_inq.get("content", ""),
                "received_at": ext_inq.get("received_at", datetime.datetime.utcnow().isoformat()),
                "status": "pending",
                "order_number": ext_inq.get("order_number"),
                "item_name": ext_inq.get("item_name"),
                "item_number": ext_inq.get("item_number"),
                "category": ext_inq.get("category"),
                "inquiry_type": ext_inq.get("type"),
            }
            inq_res = supabase.table("inquiries").insert(new_data).execute()
            if inq_res.data:
                result["inserted"] += 1
                new_inq_id = inq_res.data[0]["id"]
                print(f"    ✅ INSERT #{rakuten_id} ({ext_inq.get('customer_id')})", flush=True)
                
                # AI 초안 생성 + 카테고리/감정 분석
                try:
                    from app.core.ai_client import ai_client
                    ai_result = await ai_client.generate_reply(
                        inquiry_text=new_data["content"],
                        context=new_data
                    )
                    
                    # 카테고리, 감정, 태그, 우선순위 업데이트
                    supabase.table("inquiries").update({
                        "category": ai_result.get("category", "その他"),
                        "sentiment": ai_result.get("sentiment"),
                        "sentiment_score": ai_result.get("sentiment_score"),
                        "ai_tags": ai_result.get("tags"),
                        "priority": ai_result.get("priority_suggestion")
                    }).eq("id", new_inq_id).execute()
                    
                    # AI 초안 저장
                    supabase.table("reply_drafts").insert({
                        "company_id": company_id,
                        "inquiry_id": new_inq_id,
                        "ai_suggested_reply": ai_result.get("reply", "エラー"),
                        "status": "draft"
                    }).execute()
                    
                    print(f"    📝 AI 초안 생성 완료 #{rakuten_id}", flush=True)
                except Exception as ai_err:
                    print(f"    ⚠️ AI 초안 생성 실패 #{rakuten_id}: {ai_err}", flush=True)
        except Exception as e:
            result["errors"].append(f"INSERT {rakuten_id}: {str(e)}")
            print(f"    ❌ INSERT 실패 #{rakuten_id}: {e}", flush=True)

    # 5. RMS에서 완료/답변된 문의 DELETE (관련 데이터 포함)
    for rakuten_id in to_delete:
        db_id = db_map[rakuten_id]
        try:
            # 관련 데이터 먼저 삭제 (외래키 제약)
            supabase.table("reply_drafts").delete().eq("inquiry_id", db_id).execute()
            supabase.table("internal_notes").delete().eq("inquiry_id", db_id).execute()
            # 문의 삭제
            supabase.table("inquiries").delete().eq("id", db_id).execute()
            result["deleted"] += 1
            print(f"    🗑️ DELETE #{rakuten_id} (RMS에서 완료됨)", flush=True)
        except Exception as e:
            result["errors"].append(f"DELETE {rakuten_id}: {str(e)}")
            print(f"    ❌ DELETE 실패 #{rakuten_id}: {e}", flush=True)

    result["unchanged"] = len(unchanged)
    return result


async def reconcile_all_shops():
    """
    모든 연동 숍에 대해 reconciliation을 수행합니다.
    """
    print("\n[Sync] === Reconciliation 동기화 시작 ===", flush=True)

    from dotenv import load_dotenv
    load_dotenv()

    admin_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or settings.SUPABASE_KEY
    supabase: Client = create_client(settings.SUPABASE_URL, admin_key)

    try:
        shops_res = supabase.table("connected_shops").select("*").execute()
        shops = shops_res.data or []
        rakuten_shops = [s for s in shops if s["platform"] == "rakuten"]

        print(f"[Sync] Rakuten 숍 {len(rakuten_shops)}개 발견", flush=True)

        all_results = []
        for shop in rakuten_shops:
            shop_result = await reconcile_shop_inquiries(shop, supabase)
            all_results.append(shop_result)

        # 전체 집계
        total_inserted = sum(r["inserted"] for r in all_results)
        total_deleted = sum(r["deleted"] for r in all_results)
        total_unchanged = sum(r["unchanged"] for r in all_results)
        total_errors = sum(len(r["errors"]) for r in all_results)

        summary = f"동기화 완료: 신규 {total_inserted}건, 삭제 {total_deleted}건, 유지 {total_unchanged}건"
        if total_errors > 0:
            summary += f", 에러 {total_errors}건"

        print(f"[Sync] === {summary} ===\n", flush=True)

        return {
            "summary": summary,
            "shops": all_results,
            "totals": {
                "inserted": total_inserted,
                "deleted": total_deleted,
                "unchanged": total_unchanged,
                "errors": total_errors,
            }
        }

    except Exception as e:
        import traceback
        print(f"❌ [Sync] Critical Error: {e}", flush=True)
        traceback.print_exc()
        return {"summary": f"에러 발생: {str(e)}", "shops": [], "totals": {}}


async def start_bot():
    """
    FastAPI 서버 시작 시 호출되어 스케줄러를 시작합니다.
    """
    async def delayed_start():
        await asyncio.sleep(5)
        print("[Sync Bot] 서버 안정화 완료. 첫 번째 동기화 시작...", flush=True)
        await reconcile_all_shops()

    asyncio.create_task(delayed_start())

    # 스케줄러 등록 (10분 간격)
    if not scheduler.running:
        scheduler.add_job(reconcile_all_shops, 'interval', minutes=10)
        scheduler.start()
        print("[Sync Bot] 스케줄러 시작 (10분 주기 reconciliation)", flush=True)
