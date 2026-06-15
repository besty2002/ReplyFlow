from fastapi import APIRouter, Request, Depends, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase import create_client, ClientOptions
import httpx
import math
import traceback
import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote

from app.core.config import settings
from app.core.security import verify_supabase_jwt

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
JST = ZoneInfo("Asia/Tokyo")


def format_jst_datetime(value: str | None) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return "-"

async def get_web_user_context(sb_access_token: str | None = Cookie(default=None, alias="sb-access-token")) -> dict | None:
    """ 
    テンプレート レンダリング 시점에 クッキーで JWT를 읽어 유저 情報를 디코딩하고 소속 会社를 確認します. 
    期限切れ되었거나 情報がなければ 例外 대신 None을 返却하여 ページで リダイレクト 処理します.
    """
    if not sb_access_token:
        return None
    try:
        # 1. トークン 자체 有効성 検証
        payload = verify_supabase_jwt(sb_access_token)
        user_id = payload.get("sub")
        
        # 2. 파이썬 クライアント의 ヘッダー 오버라이드 문제를 피하기 ために httpx로 REST를 直接 呼び出し (RLS 통과 목적)
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
                return {"error": f"API ステータスコード 200이 아니거나 データ가 비어あります. レスポンス: {resp.text}"}
    except Exception as e:
        # 期限切れ되었거나 조작된 クッキー
        return {"error": f"자격 증명 検証 중 エラーが発生しました: {str(e)}"}

@router.get("/", response_class=RedirectResponse)
async def root_redirect():
    """ 최상위 アクセス 시 自動で ダッシュボード로 유도 """
    return RedirectResponse(url="/dashboard")

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user_context: dict | None = Depends(get_web_user_context)):
    # 정상적で ログ인된 ステータス라면 라우팅 이동
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

    # 페이징 및 フィルター 設定
    page_size = 20
    offset = (page - 1) * page_size
    
    inquiries = []
    connected_shops = []
    unique_categories = []
    total_count = 0
    total_pages = 1
    sync_status = None

    if sb_access_token:
        # 1. フィルター용 ショップ リスト 取得
        shop_url = f"{settings.SUPABASE_URL}/rest/v1/connected_shops?select=id,shop_name,platform"
        
        # 2. 실データ 기반 유니크 カテゴリー リスト 取得 (フィルター용)
        # category カラム이 null이 아닌 것들 중 유니크한 値만 抽出
        category_url = f"{settings.SUPABASE_URL}/rest/v1/inquiries?select=category&category=not.is.null"
        
        headers = {
            "apikey": settings.SUPABASE_KEY,
            "Authorization": f"Bearer {sb_access_token}"
        }
        
        # 3. お問い合わせ クエリ 구성 (미処理 データ만 基本 노출)
        query_params = "select=*,reply_drafts(*),connected_shops(*)&order=received_at.desc&status=eq.pending"
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
        
        # 4. 통계 データ 取得 (Dashboard Widgets)
        stats = {"pending_inquiries": 0, "pending_drafts": 0, "sent_today": 0}
        today_start = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        
        try:
            async with httpx.AsyncClient() as client:
                # ショップ リスト 수집
                shop_res = await client.get(shop_url, headers=headers)
                if shop_res.status_code == 200:
                    connected_shops = shop_res.json()
                    
                    # --- [추가] API 키 만료 임박 체크 (7일 이내) ---
                    now = datetime.datetime.now(datetime.timezone.utc)
                    warning_threshold = now + datetime.timedelta(days=7)
                    expiring_shops = []
                    for s in connected_shops:
                        if s.get("expires_at"):
                            try:
                                exp_date = datetime.datetime.fromisoformat(s["expires_at"].replace('Z', '+00:00'))
                                if now <= exp_date <= warning_threshold:
                                    # 남은 일수 계산
                                    diff = exp_date - now
                                    s["days_left"] = diff.days if diff.days >= 0 else 0
                                    expiring_shops.append(s)
                            except: pass
                    # ------------------------------------------
                
                # カテゴリー リスト 수집 및 유니크 処理
                cat_res = await client.get(category_url, headers=headers)
                if cat_res.status_code == 200:
                    raw_cats = [c.get("category") for c in cat_res.json() if c.get("category")]
                    unique_categories = sorted(list(set(raw_cats)))

                sync_res = await client.get(
                    f"{settings.SUPABASE_URL}/rest/v1/sync_status?sync_key=eq.rakuten_reconcile&select=*",
                    headers=headers
                )
                if sync_res.status_code == 200 and sync_res.json():
                    sync_status = sync_res.json()[0]
                    sync_status["last_started_at_jst"] = format_jst_datetime(sync_status.get("last_started_at"))
                    sync_status["last_completed_at_jst"] = format_jst_datetime(sync_status.get("last_completed_at"))
                    sync_status["updated_at_jst"] = format_jst_datetime(sync_status.get("updated_at"))
                
                # お問い合わせ リスト 수집
                res = await client.get(inquiry_url, headers=inquiry_headers)
                if res.status_code in [200, 206]:
                    inquiries = res.json()
                    content_range = res.headers.get("Content-Range", "")
                    if "/" in content_range:
                        total_count = int(content_range.split("/")[-1])
                    else: total_count = len(inquiries)
                    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1
                
                # --- [통계용 追加 クエリ] ---
                # 1. 待機 중인 お問い合わせ 카운트
                pending_inq_url = f"{settings.SUPABASE_URL}/rest/v1/inquiries?status=eq.pending&select=id"
                p_res = await client.get(pending_inq_url, headers={**headers, "Prefer": "count=exact", "Range": "0-0"})
                if p_res.status_code in [200, 206]:
                    stats["pending_inquiries"] = int(p_res.headers.get("Content-Range", "0/0").split("/")[-1])

                # 2. 承認 待機 중인 返信(Drafts) 카운트
                pending_draft_url = f"{settings.SUPABASE_URL}/rest/v1/reply_drafts?status=eq.draft&select=id"
                d_res = await client.get(pending_draft_url, headers={**headers, "Prefer": "count=exact", "Range": "0-0"})
                if d_res.status_code in [200, 206]:
                    stats["pending_drafts"] = int(d_res.headers.get("Content-Range", "0/0").split("/")[-1])

                # 3. 오늘 送信 完了된 카운트 (replied ステータス이고 updated_at 이 오늘인 것)
                sent_today_url = f"{settings.SUPABASE_URL}/rest/v1/inquiries?status=eq.replied&updated_at=gte.{quote(today_start, safe='')}&select=id"
                s_res = await client.get(sent_today_url, headers={**headers, "Prefer": "count=exact", "Range": "0-0"})
                if s_res.status_code in [200, 206]:
                    stats["sent_today"] = int(s_res.headers.get("Content-Range", "0/0").split("/")[-1])
        except Exception as e:
            print("❌ DB 照会 중 エラー:", e)
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
            "stats": stats,
            "expiring_shops": expiring_shops if 'expiring_shops' in locals() else [],
            "sync_status": sync_status,
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
            print("DB 照会 시 エラー:", e)
            
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
        
        # 1. 상점 リスト
        async with httpx.AsyncClient() as client:
            shop_res = await client.get(f"{settings.SUPABASE_URL}/rest/v1/connected_shops", headers=headers)
            if shop_res.status_code == 200:
                connected_shops = shop_res.json()
            
            # 2. お問い合わせ リスト フィルタリング クエリ
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

@router.get("/inquiries/{inquiry_id}/chat", response_class=HTMLResponse)
async def inquiry_chat_page(
    request: Request,
    inquiry_id: str,
    user_context: dict | None = Depends(get_web_user_context)
):
    if not user_context or "error" in user_context:
        return RedirectResponse(url="/login")
        
    sb_access_token = request.cookies.get("sb-access-token")
    inquiry = {}
    draft_reply = ""
    
    if sb_access_token:
        headers = {
            "apikey": settings.SUPABASE_KEY,
            "Authorization": f"Bearer {sb_access_token}"
        }
        async with httpx.AsyncClient() as client:
            inq_url = f"{settings.SUPABASE_URL}/rest/v1/inquiries?id=eq.{inquiry_id}&select=*,reply_drafts(*),connected_shops(*)"
            res = await client.get(inq_url, headers=headers)
            if res.status_code == 200 and res.json():
                inquiry = res.json()[0]
                if inquiry.get("reply_drafts") and len(inquiry["reply_drafts"]) > 0:
                    draft_reply = inquiry["reply_drafts"][0].get("ai_suggested_reply", "")

    return templates.TemplateResponse(
        request=request,
        name="inquiry_thread.html",
        context={
            "user_context": user_context,
            "inquiry": inquiry,
            "draft_reply": draft_reply
        }
    )

@router.get("/training", response_class=HTMLResponse)
async def training_page(request: Request, user_context: dict | None = Depends(get_web_user_context)):
    if not user_context or "error" in user_context:
        return RedirectResponse(url="/login")
    
    # 훈련 리뷰 ページ テンプレート은 아직 없으므로 간단히 レンダリング하거나 추후 生成
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
