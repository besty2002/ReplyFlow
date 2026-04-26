import asyncio
import os
import sys

# 프로젝트 루트를 경로에 추가
sys.path.append(os.getcwd())

from supabase import create_client
from app.core.config import settings
from app.core.rakuten_client import RakutenRMSClient

async def debug_run():
    print("\n" + "="*50)
    print("🚀 [Debug Bot] 실전 진단 모드 시작!")
    print("="*50)
    
    # 1. Supabase 연결 체크
    print(f"🔗 Supabase URL: {settings.SUPABASE_URL}")
    try:
        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        print("✅ Supabase 연결 성공!")
        
        # 2. 등록된 숍 정보 조회
        print("🔍 연동된 숍 목록 조회 중...")
        res = supabase.table("connected_shops").select("*").execute()
        shops = res.data
        
        if not shops:
            print("❌ 연동된 숍이 한 건도 없습니다! 비즈니스 설정에서 숍을 먼저 등록해주세요.")
            return

        print(f"✅ 총 {len(shops)}개의 숍을 발견했습니다.")
        
        for s in shops:
            print(f"\n--- [{s['platform'].upper()}] {s['shop_name']} 숍 진단 ---")
            
            if s['platform'] == 'rakuten':
                api_key = s['api_key']
                api_secret = s.get('api_secret', '')
                
                print(f"📡 라쿠텐 API 호출 시도... (Key: {api_key[:5]}*** / Secret: {api_secret[:5]}***)")
                
                rakuten = RakutenRMSClient(service_secret=api_key, license_key=api_secret)
                inquiries = rakuten.get_inquiry_list()
                
                print(f"📊 수집 결과: {len(inquiries)}건의 문의를 발견했습니다.")
                for i in inquiries:
                    print(f"   - [ID: {i.get('rakuten_inquiry_id')}] {i.get('title')[:20]}...")
            else:
                print(f"ℹ️ {s['platform']} 플랫폼은 현재 진단 대상이 아닙니다.")
                
    except Exception as e:
        print(f"❌ 진단 중 치명적 에러 발생: {str(e)}")
    
    print("\n" + "="*50)
    print("✨ [Debug Bot] 진단 종료")
    print("="*50 + "\n")

if __name__ == "__main__":
    asyncio.run(debug_run())
