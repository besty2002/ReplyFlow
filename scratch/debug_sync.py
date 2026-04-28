"""
디버그 스크립트: Rakuten RMS API에서 문의를 정상적으로 가져오는지 확인합니다.
"""
import asyncio
import os
import sys

# 프로젝트 루트를 패스에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.core.config import settings
from supabase import create_client

async def debug_sync():
    print("=" * 60)
    print("[DEBUG] Rakuten RMS Inquiry Fetch Diagnostic")
    print("=" * 60)
    
    # 1. Supabase 연결 확인
    admin_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SERVICE_ROLE_KEY") or settings.SUPABASE_KEY
    supabase = create_client(settings.SUPABASE_URL, admin_key)
    print(f"\n✅ Supabase URL: {settings.SUPABASE_URL}")
    print(f"   Key type: {'ServiceRole' if admin_key != settings.SUPABASE_KEY else 'AnonKey'}")
    
    # 2. 연동된 숍 목록 확인
    shops_res = supabase.table("connected_shops").select("*").execute()
    shops = shops_res.data
    print(f"\n📦 연동된 숍 수: {len(shops) if shops else 0}")
    
    if not shops:
        print("❌ 연동된 숍이 없습니다! 설정 페이지에서 숍을 먼저 등록하세요.")
        return
    
    for i, shop in enumerate(shops):
        print(f"\n--- Shop #{i+1} ---")
        print(f"   Platform: {shop['platform']}")
        print(f"   Name:     {shop['shop_name']}")
        print(f"   Active:   {shop.get('is_active', 'N/A')}")
        print(f"   API Key:  {shop.get('api_key', 'N/A')[:8]}***")
        print(f"   API Secret: {shop.get('api_secret', 'N/A')[:8]}***")
        print(f"   Company ID: {shop.get('company_id')}")
        print(f"   Shop ID:   {shop.get('id')}")
    
    # 3. Rakuten API 호출 테스트
    rakuten_shops = [s for s in shops if s["platform"] == "rakuten"]
    
    if not rakuten_shops:
        print("\n⚠️ Rakuten 플랫폼의 숍이 없습니다.")
        return
    
    for shop in rakuten_shops:
        print(f"\n{'='*60}")
        print(f"🔍 [{shop['shop_name']}] Rakuten API 호출 테스트")
        print(f"{'='*60}")
        
        from app.core.rakuten_client import RakutenRMSClient
        import datetime
        
        rakuten = RakutenRMSClient(
            service_secret=shop["api_key"],
            license_key=shop.get("api_secret", "")
        )
        
        # 날짜 범위 확인
        now = datetime.datetime.now()
        start_date = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")
        end_date = now.strftime("%Y-%m-%dT%H:%M:%S")
        print(f"   검색 기간: {start_date} ~ {end_date}")
        
        # Raw API 호출 (파싱 전)
        import httpx
        endpoint = "https://api.rms.rakuten.co.jp/es/1.0/inquirymng-api/inquiries"
        params = {
            "fromDate": start_date,
            "toDate": end_date,
            "limit": 50,
            "page": 1,
            "noMerchantReply": "true"
        }
        
        print(f"\n📡 API 호출 시작...")
        print(f"   Endpoint: {endpoint}")
        print(f"   Params: {params}")
        print(f"   Headers Auth: ESA {rakuten.headers['Authorization'][:20]}...")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(endpoint, headers=rakuten.headers, params=params)
            
            print(f"\n📥 응답 코드: {res.status_code}")
            
            if res.status_code == 200:
                json_data = res.json()
                total_pages = json_data.get("totalPageCount", 1)
                total_count = json_data.get("totalCount", "N/A")
                inquiry_list = json_data.get("list", [])
                
                print(f"   총 페이지: {total_pages}")
                print(f"   총 문의 수: {total_count}")
                print(f"   현재 페이지 문의 수: {len(inquiry_list)}")
                
                # 각 문의 상세 출력
                for j, item in enumerate(inquiry_list):
                    inq_no = item.get("inquiryNumber", "N/A")
                    is_completed = item.get("isCompleted", False)
                    user_name = item.get("userName", "N/A")
                    reg_date = item.get("regDate", item.get("inquiryDateTime", "N/A"))
                    order_num = item.get("orderNumber", "N/A")
                    
                    # 답변 상태 확인
                    replies = item.get("replies", [])
                    has_merchant_reply = any(r.get("replyFrom") == "merchant" for r in replies)
                    
                    status = "🔴 SKIP(완료)" if is_completed else ("🟡 SKIP(답변완료)" if has_merchant_reply else "🟢 수집대상")
                    
                    print(f"\n   [{j+1}] 문의번호: {inq_no} | {status}")
                    print(f"       고객: {user_name} | 주문: {order_num}")
                    print(f"       등록일: {reg_date} | 완료여부: {is_completed}")
                    print(f"       답변수: {len(replies)} | 상점답변: {'있음' if has_merchant_reply else '없음'}")
                    
                    content = item.get("meessage") or item.get("message") or ""
                    print(f"       내용 미리보기: {content[:80]}...")
                
                # noMerchantReply 필터 없이도 조회
                print(f"\n\n{'='*60}")
                print(f"🔍 [비교] noMerchantReply 필터 제거하고 재조회")
                print(f"{'='*60}")
                
                params_all = {
                    "fromDate": start_date,
                    "toDate": end_date,
                    "limit": 50,
                    "page": 1,
                }
                res_all = await client.get(endpoint, headers=rakuten.headers, params=params_all)
                if res_all.status_code == 200:
                    data_all = res_all.json()
                    total_all = data_all.get("totalCount", "N/A")
                    list_all = data_all.get("list", [])
                    print(f"   총 문의 수 (필터 없음): {total_all}")
                    print(f"   현재 페이지 문의 수: {len(list_all)}")
                    
                    # 필터된 결과와 차이 표시
                    filtered_ids = set(item.get("inquiryNumber") for item in inquiry_list)
                    for item in list_all:
                        inq_no = item.get("inquiryNumber")
                        if inq_no not in filtered_ids:
                            print(f"   ⚡ 필터로 제외된 문의: {inq_no} (isCompleted={item.get('isCompleted')}, 답변수={len(item.get('replies', []))})")
                else:
                    print(f"   ❌ 필터 없는 조회도 실패: {res_all.status_code} {res_all.text}")

            else:
                print(f"   ❌ API 응답 본문: {res.text[:500]}")
        
        # 4. DB에 이미 있는 문의 확인
        print(f"\n\n{'='*60}")
        print(f"🗄️ DB 내 기존 문의 현황")
        print(f"{'='*60}")
        
        db_inquiries = supabase.table("inquiries").select("id, rakuten_inquiry_id, status, received_at, customer_id").eq("shop_id", shop["id"]).order("received_at", desc=True).limit(20).execute()
        
        if db_inquiries.data:
            print(f"   총 {len(db_inquiries.data)}건 (최근 20건 표시)")
            for inq in db_inquiries.data:
                print(f"   - [{inq['status']}] {inq['rakuten_inquiry_id']} | {inq.get('customer_id', 'N/A')} | {inq.get('received_at', 'N/A')[:16]}")
        else:
            print(f"   DB에 해당 숍의 문의가 없습니다.")

    print(f"\n\n{'='*60}")
    print(f"✅ 진단 완료")
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(debug_sync())
