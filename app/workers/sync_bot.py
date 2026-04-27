import asyncio
import os
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from supabase import create_client, Client
from app.core.config import settings
from app.core.ai_client import ai_client
from app.core.rakuten_client import RakutenRMSClient
import uuid
import datetime

logger = logging.getLogger(__name__)

# 스케줄러 전역 인스턴스
scheduler = AsyncIOScheduler()

async def fetch_and_process_inquiries():
    """
    주기적으로 모든 active 숍의 새 문의를 수집하고 AI 분류를 거쳐 DB에 저장합니다.
    """
    logger.info("[Sync Bot] Shops external inquiry synchronization scheduler running...")
    
    # .env 파일 강제 로드 (봇 환경에서 누락 방지)
    from dotenv import load_dotenv
    load_dotenv()
    
    # Supabase 서비스 키를 우선적으로 사용 (보안 정책 우회용 관리자 권한)
    admin_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SERVICE_ROLE_KEY") or settings.SUPABASE_KEY
    supabase: Client = create_client(settings.SUPABASE_URL, admin_key)
    
    # [디버그] 연결 권한 확인
    print(f"[Sync Bot] Permission check: {'Master' if 'ey' in admin_key[:10] else 'Anon'}")
    
    try:
        print(f"[Sync Bot] DB connection attempt... (URL: {settings.SUPABASE_URL})")
        # [긴급] 모든 보안 정책을 무시하고 테이블의 전 데이터를 긁어옵니다.
        # RLS가 걸려있어도 service_role_key를 쓰면 이 쿼리로 다 가져옵니다.
        shops_res = supabase.table("connected_shops").select("*").execute()
        active_shops = shops_res.data
        
        print(f"[Sync Bot] Number of shops queried: {len(active_shops) if active_shops else 0} cases")
        
        if not active_shops:
            print("[Sync Bot] No shop information linked to the DB! Please register a shop in business settings first.")
            return

        for shop in active_shops:
            platform = shop["platform"]
            shop_name = shop["shop_name"]
            api_key = shop.get("api_key")
            api_secret = shop.get("api_secret")
            company_id = shop.get("company_id")
            shop_id = shop.get("id")
            
            print(f"[Sync Bot] {platform.upper()} platform '{shop_name}' collection started...")
            
            # TODO: 실제 프로덕션에서는 각 platform API(Rakuten SDK 등)를 호출하여 새 문의를 가져옵니다.
            # 여기서는 API 연동 시뮬레이션을 위해 "조건부 목업"을 주입합니다.
            
            # --- [실제 API 호출 로직 시작] ---
            fetched_inquiries = []
            
            if platform == "rakuten":
                # 라쿠텐 실전 클라이언트 기동 (비동기 처리)
                rakuten = RakutenRMSClient(service_secret=api_key, license_key=shop.get("api_secret", ""))
                fetched_inquiries = await rakuten.get_inquiry_list()
            
            # TODO: 야후, 큐텐 등 다른 플랫폼 클라이언트도 이곳에 추가 가능
            
            for ext_inq in fetched_inquiries:
                raw_id = ext_inq["rakuten_inquiry_id"]
                
                # 1. 중복 수집 방지 (이미 DB에 있는지 체크)
                exists = supabase.table("inquiries").select("id").eq("rakuten_inquiry_id", raw_id).execute()
                if exists.data:
                    continue # 이미 수집된 문의는 스킵

                logger.info(f"👉 [{platform.upper()}] 新規問い合わせ収集: {raw_id}")
                
                new_inquiry_data = {
                    "company_id": company_id,
                    "shop_id": shop_id,
                    "rakuten_inquiry_id": raw_id,
                    "customer_id": ext_inq.get("customer_id", "Unknown"),
                    "title": ext_inq.get("title", "No Title"),
                    "content": ext_inq.get("content", ""),
                    "received_at": ext_inq.get("received_at", datetime.datetime.utcnow().isoformat()),
                    "status": "pending",
                    "order_number": ext_inq.get("order_number"),
                    "item_name": ext_inq.get("item_name"),
                    "item_number": ext_inq.get("item_number"),
                    "category": ext_inq.get("category"),
                    "inquiry_type": ext_inq.get("type")
                }
                
                # 2. DB 저장
                inq_res = supabase.table("inquiries").insert(new_inquiry_data).execute()
                if not inq_res.data:
                    logger.error(f"❌ [{platform.upper()}] DB 저장 실패: {raw_id}")
                    continue
                    
                new_inq_id = inq_res.data[0]["id"]
                
                # 3. AI 초안 생성 및 분류 (고객 이름 등 Context 포함)
                ai_result = await ai_client.generate_reply(
                    inquiry_text=new_inquiry_data["content"],
                    context=new_inquiry_data
                )
                
                # 4. 카테고리, 감정, 태그, 우선순위 업데이트 및 초안 저장
                supabase.table("inquiries").update({
                    "category": ai_result.get("category", "その他"),
                    "sentiment": ai_result.get("sentiment"),
                    "sentiment_score": ai_result.get("sentiment_score"),
                    "ai_tags": ai_result.get("tags"),
                    "priority": ai_result.get("priority_suggestion")
                }).eq("id", new_inq_id).execute()

                supabase.table("reply_drafts").insert({
                    "company_id": company_id,
                    "inquiry_id": new_inq_id,
                    "ai_suggested_reply": ai_result.get("reply", "エラー"),
                    "status": "draft"
                }).execute()
                
                logger.info(f"✅ [{platform.upper()}] 連携完了 (Inquiry ID: {new_inq_id})")
            # --- [실제 API 호출 로직 끝] ---
            
    except Exception as e:
        logger.error(f"❌ [Sync Bot] Critical Error: {e}")

async def start_bot():
    """
    FastAPI 등 구동 시 호출되어 스케줄러를 시작합니다.
    """
    # 백그라운드 태스크로 봇 실행 (5초 딜레이를 주어 서버 응답성 우선 확보)
    async def delayed_start():
        await asyncio.sleep(5)
        logger.info("[Sync Bot] Server stabilized. Starting first collection...")
        await fetch_and_process_inquiries()

    asyncio.create_task(delayed_start())
    
    # 스케줄러 등록 (10분 간격으로 단축하여 더 빠른 동기화 제공)
    if not scheduler.running:
        scheduler.add_job(fetch_and_process_inquiries, 'interval', minutes=10)
        scheduler.start()
        logger.info("[Sync Bot] Scheduler operation complete (10 minute cycle)")
