import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.api.endpoints import auth, pages, inquiries, training, shops, user
from app.workers.sync_bot import start_bot


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "=" * 50)
    print("[START] Server Startup")
    print("=" * 50 + "\n")

    # Reconciliation 기반 sync_bot 시작 (5초 딜레이 후 자동 실행)
    try:
        asyncio.create_task(start_bot())
        print("[OK] Sync bot (reconciliation) started")
    except Exception as e:
        print(f"[WARN] Failed to start sync bot: {e}")

    yield

    print("[STOP] Server Shutdown")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="일본 EC 판매자용 고객문의 자동처리 SaaS API",
    version="1.0.0",
    lifespan=lifespan,
)

# 개발용 CORS 설정
# allow_origins=["*"] 사용 시 allow_credentials=False 권장
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static Assets
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# Health check
@app.get("/health")
def health_check():
    return {"status": "ok"}


# Router
app.include_router(pages.router, tags=["pages"])
app.include_router(user.router, prefix=f"{settings.API_V1_STR}/user", tags=["user"])
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(inquiries.router, prefix=f"{settings.API_V1_STR}/inquiries", tags=["inquiries"])
app.include_router(training.router, prefix=f"{settings.API_V1_STR}/training", tags=["training"])
app.include_router(shops.router, prefix=f"{settings.API_V1_STR}/shops", tags=["shops"])


# 관리자용 수동 동기화 엔드포인트
# 사용법: 브라우저에서 http://127.0.0.1:8000/admin/sync 접속
@app.get("/admin/sync")
async def admin_sync():
    """RMS 未返信 목록과 DB를 대조하여 동기화 (신규 추가 + 완료된 건 삭제)"""
    from app.workers.sync_bot import reconcile_all_shops
    result = await reconcile_all_shops()
    return result


# 기존 purge-and-resync도 유지 (호환성)
@app.get("/admin/purge-and-resync")
async def admin_purge_and_resync():
    """전체 삭제 후 재수집 (긴급용)"""
    import os
    from dotenv import load_dotenv
    from supabase import create_client
    from app.core.rakuten_client import RakutenRMSClient
    import datetime

    load_dotenv()
    print("[Admin] purge-and-resync 시작...", flush=True)

    admin_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or settings.SUPABASE_KEY
    supabase = create_client(settings.SUPABASE_URL, admin_key)

    result = {"steps": [], "errors": []}

    # 1. 기존 데이터 전체 삭제
    for table in ["reply_drafts", "send_logs", "ai_training_logs", "internal_notes", "inquiries"]:
        try:
            res = supabase.table(table).delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
            count = len(res.data) if res.data else 0
            result["steps"].append(f"{table}: {count}건 삭제")
            print(f"  [삭제] {table}: {count}건", flush=True)
        except Exception as e:
            result["errors"].append(f"{table}: {str(e)}")

    # 2. 未返信 문의 재수집
    shops_res = supabase.table("connected_shops").select("*").execute()
    rakuten_shops = [s for s in (shops_res.data or []) if s["platform"] == "rakuten"]

    new_count = 0
    for shop in rakuten_shops:
        print(f"  [API] {shop['shop_name']} 수집 중...", flush=True)
        rakuten = RakutenRMSClient(service_secret=shop["api_key"], license_key=shop.get("api_secret", ""))
        fetched = await rakuten.get_inquiry_list()
        result["steps"].append(f"Rakuten API: {len(fetched)}건 수신 (未返信만)")
        print(f"  [API] {len(fetched)}건 수신 완료", flush=True)

        for ext_inq in fetched:
            try:
                new_data = {
                    "company_id": shop.get("company_id"),
                    "shop_id": shop.get("id"),
                    "rakuten_inquiry_id": ext_inq["rakuten_inquiry_id"],
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
                    new_count += 1
                    print(f"    ✅ #{ext_inq['rakuten_inquiry_id']} 저장", flush=True)
            except Exception as e:
                result["errors"].append(f"문의 {ext_inq['rakuten_inquiry_id']}: {str(e)}")

    result["summary"] = f"완료! 未返信 {new_count}건 수집 완료"
    result["total_collected"] = new_count
    print(f"  [완료] 未返信 {new_count}건 수집 완료", flush=True)
    return result