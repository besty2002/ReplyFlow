from fastapi import APIRouter, Request, Depends, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase import create_client, ClientOptions
import httpx
import math
import traceback
import datetime

from app.core.config import settings
from app.core.security import verify_supabase_jwt

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

async def get_web_user_context(sb_access_token: str | None = Cookie(default=None, alias="sb-access-token")) -> dict | None:
    """ 
    템플릿 렌더링 시점에 쿠키에서 JWT를 읽어 유저 정보를 디코딩하고 소속 회사를 확인합니다. 
    만료되었거나 정보가 없으면 예외 대신 None을 반환하여 페이지에서 리다이렉트 처리합니다.
    """
    if not sb_access_token:
        return None
    try:
        # 1. 토큰 자체 유효성 검증
        payload = verify_supabase_jwt(sb_access_token)
        user_id = payload.get("sub")
        
        # 2. 파이썬 클라이언트의 헤더 오버라이드 문제를 피하기 위해 httpx로 REST를 직접 호출 (RLS 통과 목적)
        url = f"{settings.SUPABASE_URL}/rest/v1/company_users?user_id=eq.{user_id}&select=company_id,role"
        headers = {
            "apikey": settings.SUPABASE_KEY,
            "Authorization": f"Bearer {sb_access_token}"
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200 and resp.json():
                context = resp.json()[0]
                context['user_id'] = user_id
                return context
            else:
                return {"error": f"API 상태코드 200이 아니거나 데이터가 비어있습니다. 응답: {resp.text}"}
    except Exception as e:
        # 만료되었거나 조작된 쿠키
        return {"error": f"자격 증명 검증 중 오류 발생: {str(e)}"}

@router.get("/", response_class=RedirectResponse)
async def root_redirect():
    """ 최상위 접근 시 자동으로 대시보드로 유도 """
    return RedirectResponse(url="/dashboard")

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user_context: dict | None = Depends(get_web_user_context)):
    # 정상적으로 로그인된 상태라면 라우팅 이동
    if user_context and "error" not in user_context:
        return RedirectResponse(url="/dashboard")
        
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "conf_supabase_url": settings.SUPABASE_URL,
            "conf_supabase_key": settings.SUPABASE_KEY,
        }
    )

@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request, user_context: dict | None = Depends(get_web_user_context)):
    if user_context and "error" not in user_context:
        return RedirectResponse(url="/dashboard")
        
    return templates.TemplateResponse(
        request=request,
        name="signup.html",
        context={
            "conf_supabase_url": settings.SUPABASE_URL,
            "conf_supabase_key": settings.SUPABASE_KEY,
        }
    )

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, user_context: dict | None = Depends(get_web_user_context), page: int = 1, shop_id: str | None = None, category: str | None = None):
    if not user_context or "error" in user_context:
        return RedirectResponse(url="/login")

    sb_access_token = request.cookies.get("sb-access-token")

    # 페이징 및 필터 설정
    page_size = 20
    offset = (page - 1) * page_size
    
    inquiries = []
    connected_shops = []
    unique_categories = []
    total_count = 0
    total_pages = 1

    if sb_access_token:
        # 1. 필터용 숍 목록 가져오기
        shop_url = f"{settings.SUPABASE_URL}/rest/v1/connected_shops?select=id,shop_name,platform"
        
        # 2. 실데이터 기반 유니크 카테고리 목록 가져오기 (필터용)
        # category 컬럼이 null이 아닌 것들 중 유니크한 값만 추출
        category_url = f"{settings.SUPABASE_URL}/rest/v1/inquiries?select=category&category=not.is.null"
        
        headers = {
            "apikey": settings.SUPABASE_KEY,
            "Authorization": f"Bearer {sb_access_token}"
        }
        
        # 3. 문의 쿼리 구성 (미처리 데이터만 기본 노출)
        query_params = "select=*,reply_drafts(*),connected_shops(*)&order=created_at.desc&status=eq.pending"
        if shop_id:
            query_params += f"&shop_id=eq.{shop_id}"
        if category:
            query_params += f"&category=eq.{category}"
            
        inquiry_url = f"{settings.SUPABASE_URL}/rest/v1/inquiries?{query_params}"
        inquiry_headers = {
            "apikey": settings.SUPABASE_KEY,
            "Authorization": f"Bearer {sb_access_token}",
            "Prefer": "count=exact",
            "Range": f"{offset}-{offset + page_size - 1}"
        }
        
        # 4. 통계 데이터 가져오기 (Dashboard Widgets)
        stats = {"pending_inquiries": 0, "pending_drafts": 0, "sent_today": 0}
        today_start = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        
        try:
            async with httpx.AsyncClient() as client:
                # 숍 목록 수집
                shop_res = await client.get(shop_url, headers=headers)
                if shop_res.status_code == 200:
                    connected_shops = shop_res.json()
                
                # 카테고리 목록 수집 및 유니크 처리
                cat_res = await client.get(category_url, headers=headers)
                if cat_res.status_code == 200:
                    raw_cats = [c.get("category") for c in cat_res.json() if c.get("category")]
                    unique_categories = sorted(list(set(raw_cats)))
                
                # 문의 목록 수집
                res = await client.get(inquiry_url, headers=inquiry_headers)
                if res.status_code in [200, 206]:
                    inquiries = res.json()
                    content_range = res.headers.get("Content-Range", "")
                    if "/" in content_range:
                        total_count = int(content_range.split("/")[-1])
                    else: total_count = len(inquiries)
                    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1
                
                # --- [통계용 추가 쿼리] ---
                # 1. 대기 중인 문의 카운트
                pending_inq_url = f"{settings.SUPABASE_URL}/rest/v1/inquiries?status=eq.pending&select=id"
                p_res = await client.get(pending_inq_url, headers={**headers, "Prefer": "count=exact", "Range": "0-0"})
                if p_res.status_code in [200, 206]:
                    stats["pending_inquiries"] = int(p_res.headers.get("Content-Range", "0/0").split("/")[-1])

                # 2. 승인 대기 중인 답변(Drafts) 카운트
                pending_draft_url = f"{settings.SUPABASE_URL}/rest/v1/reply_drafts?status=eq.draft&select=id"
                d_res = await client.get(pending_draft_url, headers={**headers, "Prefer": "count=exact", "Range": "0-0"})
                if d_res.status_code in [200, 206]:
                    stats["pending_drafts"] = int(d_res.headers.get("Content-Range", "0/0").split("/")[-1])

                # 3. 오늘 전송 완료된 카운트 (replied 상태이고 updated_at 이 오늘인 것)
                sent_today_url = f"{settings.SUPABASE_URL}/rest/v1/inquiries?status=eq.replied&updated_at=gte.{today_start}&select=id"
                s_res = await client.get(sent_today_url, headers={**headers, "Prefer": "count=exact", "Range": "0-0"})
                if s_res.status_code in [200, 206]:
                    stats["sent_today"] = int(s_res.headers.get("Content-Range", "0/0").split("/")[-1])
        except Exception as e:
            print("❌ DB 조회 중 에러:", e)
            traceback.print_exc()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "conf_supabase_url": settings.SUPABASE_URL,
            "conf_supabase_key": settings.SUPABASE_KEY,
            "user_context": user_context,
            "inquiries": inquiries,
            "connected_shops": connected_shops,
            "unique_categories": unique_categories,
            "current_page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "selected_shop": shop_id,
            "selected_category": category,
            "stats": stats
        }
    )

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user_context: dict | None = Depends(get_web_user_context)):
    if not user_context or "error" in user_context:
        return RedirectResponse(url="/login")
        
    sb_access_token = request.cookies.get("sb-access-token")
    connected_shops = []
    if sb_access_token:
        url = f"{settings.SUPABASE_URL}/rest/v1/connected_shops?order=created_at.desc"
        headers = {
            "apikey": settings.SUPABASE_KEY,
            "Authorization": f"Bearer {sb_access_token}"
        }
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    connected_shops = res.json()
        except Exception as e:
            print("DB 조회 시 에러:", e)
            
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "conf_supabase_url": settings.SUPABASE_URL,
            "conf_supabase_key": settings.SUPABASE_KEY,
            "user_context": user_context,
            "connected_shops": connected_shops
        }
    )

@router.get("/inquiries", response_class=HTMLResponse)
async def inquiries_page(
    request: Request, 
    user_context: dict | None = Depends(get_web_user_context),
    status: str | None = None,
    shop_id: str | None = None,
    sentiment: str | None = None,
    q: str | None = None
):
    if not user_context or "error" in user_context:
        return RedirectResponse(url="/login")
        
    sb_access_token = request.cookies.get("sb-access-token")
    inquiries = []
    connected_shops = []
    
    if sb_access_token:
        headers = {
            "apikey": settings.SUPABASE_KEY,
            "Authorization": f"Bearer {sb_access_token}"
        }
        
        # 1. 상점 목록
        async with httpx.AsyncClient() as client:
            shop_res = await client.get(f"{settings.SUPABASE_URL}/rest/v1/connected_shops", headers=headers)
            if shop_res.status_code == 200:
                connected_shops = shop_res.json()
            
            # 2. 문의 목록 필터링 쿼리
            query = "select=*"
            if status: query += f"&status=eq.{status}"
            if shop_id: query += f"&shop_id=eq.{shop_id}"
            if sentiment: query += f"&sentiment=eq.{sentiment}"
            if q: query += f"&or=(customer_id.ilike.*{q}*,content.ilike.*{q}*,order_number.ilike.*{q}*)"
            
            inq_url = f"{settings.SUPABASE_URL}/rest/v1/inquiries?{query}&order=received_at.desc"
            inq_res = await client.get(inq_url, headers=headers)
            if inq_res.status_code == 200:
                inquiries = inq_res.json()

    return templates.TemplateResponse(
        request=request,
        name="inquiries.html",
        context={
            "user_context": user_context,
            "inquiries": inquiries,
            "connected_shops": connected_shops,
            "selected_status": status,
            "selected_shop": shop_id,
            "selected_sentiment": sentiment,
            "search_query": q
        }
    )

@router.get("/training", response_class=HTMLResponse)
async def training_page(request: Request, user_context: dict | None = Depends(get_web_user_context)):
    if not user_context or "error" in user_context:
        return RedirectResponse(url="/login")
    
    # 훈련 리뷰 페이지 템플릿은 아직 없으므로 간단히 렌더링하거나 추후 생성
    return templates.TemplateResponse(
        request=request,
        name="training.html",
        context={"user_context": user_context}
    )

@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, user_context: dict | None = Depends(get_web_user_context)):
    if not user_context or "error" in user_context:
        return RedirectResponse(url="/login")
        
    return templates.TemplateResponse(
        request=request,
        name="profile.html",
        context={
            "conf_supabase_url": settings.SUPABASE_URL,
            "conf_supabase_key": settings.SUPABASE_KEY,
            "user_context": user_context,
        }
    )
