from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from app.core.config import settings
from app.api.endpoints import auth, pages, inquiries, training, shops
from app.workers.sync_bot import start_bot

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 스타트업 시 백그라운드 봇 실행 (서버 구동을 방해하지 않게 비동기 태스크로 분리)
    print("\n" + "🚀"*10)
    print("서버 스타트업: 백그라운드 수집 봇을 깨웁니다!")
    print("🚀"*10 + "\n")
    
    # 스타트업 시 백그라운드 봇 실행
    await start_bot()
    yield
    # 셧다운 시 스케줄러 종료 처리 필요 시 이곳에 구현

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="일본 EC 판매자용 고객문의 자동처리 SaaS API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 설정 (프론트엔드/관리자 화면 분리를 고려)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 개발 목적. 상용 배포 시에는 특정 도메인으로 제한해야 합니다.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static Assets 마운트 처리 (CSS, JS, 이미지)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 라우터 등록
app.include_router(pages.router, tags=["pages"]) # Web UI용 라우터 (/, /login, /dashboard)
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(inquiries.router, prefix=f"{settings.API_V1_STR}/inquiries", tags=["inquiries"])
app.include_router(training.router, prefix=f"{settings.API_V1_STR}/training", tags=["training"])
app.include_router(shops.router, prefix=f"{settings.API_V1_STR}/shops", tags=["shops"])

@app.get("/health")
def health_check():
    return {"status": "ok"}
