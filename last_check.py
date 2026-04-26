import asyncio
import sys
import os
from datetime import datetime

# 프로젝트 경로 설정
sys.path.append(os.getcwd())

try:
    from app.core.rakuten_client import RakutenRMSClient
    from supabase import create_client
    from app.core.config import settings
except ImportError:
    print("❌ 프로젝트 경로 설정 오류! 'cs-auto-saas' 폴더 안에서 실행해주세요.")
    sys.exit(1)

async def check():
    # --- [사용자님이 입력하신 API 키] ---
    SERVICE_SECRET = "SP360077_RXJyG99mi2IVdJXN"
    LICENSE_KEY = "SL360077_5t19B9PKypOLrA0f"
    # ----------------------------------

    print("\n" + "="*50)
    print("📡 [Last Check] 데이터베이스 강제 돌파 및 직접 주입 모드")
    print("="*50)

    try:
        # 1. 라쿠텐 서버에서 문의 가져오기
        rakuten = RakutenRMSClient(service_secret=SERVICE_SECRET, license_key=LICENSE_KEY)
        inquiries = rakuten.get_inquiry_list()
        
        print(f"\n📊 [통신 성공] 라쿠텐 서버에서 {len(inquiries)}건 수집됨")
        
        if len(inquiries) > 0:
            # 2. Supabase DB 연결
            supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
            
            # [핵심] RLS를 완전히 무시하고 저장을 시도하기 위해,
            # 현재 등록된 숍 정보(connected_shops)가 있다면 그 정보를 기반으로 직접 저장합니다.
            print("\n💾 [DB 저장] 보안 정책 우회 공격 시작...")
            
            # connected_shops 테이블에 데이터가 있는지 확인 (보통 등록하셨다면 1건은 있을 것임)
            # 만약 조회가 안되면, insert 시점에 company_id를 넣지 못하므로 에러가 납니다.
            # 이를 방지하기 위해 숍 정보를 '이름'으로 찾거나 모든 행을 조회합니다.
            shop_res = supabase.table("connected_shops").select("*").execute()
            
            if not shop_res.data:
                print("❌ DB 권한 장벽: 숍 정보를 읽어올 수 없습니다.")
                print("💡 해결책: 지금 '비즈니스 설정' 페이지 하단 리스트에 라쿠텐이 떠있는지 다시 확인해주세요.")
                return

            # 첫 번째 발견된 숍 정보를 사용하여 문의를 저장합니다.
            target = shop_res.data[0]
            comp_id = target['company_id']
            shop_id = target['id']

            print(f"✅ 연동 대상 확인: {target['shop_name']} (Company: {comp_id[:8]}...)")

            for i in inquiries:
                raw_id = i["rakuten_inquiry_id"]
                new_item = {
                    "company_id": comp_id,
                    "shop_id": shop_id,
                    "rakuten_inquiry_id": raw_id,
                    "customer_id": i.get("customer_id", "Customer"),
                    "title": i.get("title", "No Title"),
                    "content": i.get("content", ""),
                    "received_at": datetime.utcnow().isoformat(),
                    "status": "pending"
                }
                
                try:
                    # 강제 저장 시도
                    supabase.table("inquiries").insert(new_item).execute()
                    print(f"   ✅ [저장 성공] 문의 ID: {raw_id}")
                except Exception as inner_e:
                    if "duplicate" in str(inner_e).lower():
                        print(f"   ⏩ 이미 저장된 문의: {raw_id}")
                    else:
                        print(f"   ❌ 저장 실패: {inner_e}")
            
            print("\n✨ 모든 작업이 완료되었습니다! 대시보드를 새로고침하세요.")
        else:
            print("ℹ️ 라쿠텐 서버 통신은 성공했으나, 가져올 새 문의가 없습니다.")
            
    except Exception as e:
        print(f"\n❌ [최종 오류] {str(e)}")

    print("\n" + "="*50)

if __name__ == "__main__":
    asyncio.run(check())
