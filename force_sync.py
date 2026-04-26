import asyncio
import os
import sys
from datetime import datetime

# 프로젝트 경로 추가
sys.path.append(os.getcwd())

try:
    from supabase import create_client
    from app.core.config import settings
    from app.core.rakuten_client import RakutenRMSClient
    from app.core.ai_client import ai_client
except ImportError as e:
    print(f"❌ 임포트 에러: {e}")
    sys.exit(1)

async def force_sync():
    print("\n" + "🚀"*10)
    print("라쿠텐 실시간 문의 강제 수집 및 DB 저장 시작!")
    print("🚀"*10 + "\n")

    # 1. DB에서 활성화된 라쿠텐 숍 가져오기
    supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    shops = supabase.table("connected_shops").select("*").eq("platform", "rakuten").execute()
    
    if not shops.data:
        print("❌ DB에 등록된 라쿠텐 숍이 없습니다. 비즈니스 설정에서 먼저 등록해주세요.")
        return

    shop = shops.data[0]
    print(f"✅ 대상 숍 발견: {shop['shop_name']}")

    # 2. 라쿠텐 API 호출
    rakuten = RakutenRMSClient(service_secret=shop['api_key'], license_key=shop.get('api_secret', ''))
    inquiries = rakuten.get_inquiry_list()
    
    print(f"📡 라쿠텐 서버로부터 {len(inquiries)}건의 문의를 수집했습니다.")

    for inq in inquiries:
        raw_id = inq["rakuten_inquiry_id"]
        
        # 중복 체크
        exists = supabase.table("inquiries").select("id").eq("rakuten_inquiry_id", raw_id).execute()
        if exists.data:
            print(f"⏩ 이미 수집된 문의입니다 (ID: {raw_id}). 건너뜁니다.")
            continue

        # DB 저장
        new_data = {
            "company_id": shop["company_id"],
            "shop_id": shop["id"],
            "rakuten_inquiry_id": raw_id,
            "customer_id": inq.get("customer_id", "Unknown"),
            "title": inq.get("title", "No Title"),
            "content": inq.get("content", ""),
            "received_at": inq.get("received_at", datetime.utcnow().isoformat()),
            "status": "pending"
        }
        
        try:
            res = supabase.table("inquiries").insert(new_data).execute()
            inq_id = res.data[0]["id"]
            print(f"✅ DB 저장 완료: {raw_id} (Internal ID: {inq_id})")
            
            # AI 초안 생성
            print("🤖 AI 답변 생성 중...")
            ai_res = ai_client.generate_reply(new_data["content"])
            
            # 초안 저장
            supabase.table("reply_drafts").insert({
                "company_id": shop["company_id"],
                "inquiry_id": inq_id,
                "ai_suggested_reply": ai_res.get("reply", ""),
                "status": "draft"
            }).execute()
            print("📝 AI 초안 생성 및 저장 완료!")
            
        except Exception as e:
            print(f"❌ 저장 중 오류 발생: {e}")

    print("\n" + "="*50)
    print("✨ 모든 작업이 완료되었습니다! 대시보드를 새로고침하세요.")
    print("="*50 + "\n")

if __name__ == "__main__":
    asyncio.run(force_sync())
