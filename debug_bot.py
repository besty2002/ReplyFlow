import asyncio
import os
import sys

# 프로젝트 루트를 パス에 追加
sys.path.append(os.getcwd())

from supabase import create_client
from app.core.config import settings
from app.core.rakuten_client import RakutenRMSClient

async def debug_run():
    print("\n" + "="*50)
    print("🚀 [Debug Bot] 실전 진단 모드 開始!")
    print("="*50)
    
    # 1. Supabase 接続 체크
    print(f"🔗 Supabase URL: {settings.SUPABASE_URL}")
    try:
        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        print("✅ Supabase 接続 成功!")
        
        # 2. 登録된 ショップ 情報 照会
        print("🔍 連携된 ショップ リスト 照会 중...")
        res = supabase.table("connected_shops").select("*").execute()
        shops = res.data
        
        if not shops:
            print("❌ 連携된 ショップ이 한 件도 ありません! 비즈니스 設定で ショップ을 먼저 登録してください.")
            return

        print(f"✅ 合計 {len(shops)}件의 ショップ을 발견しました.")
        
        for s in shops:
            print(f"\n--- [{s['platform'].upper()}] {s['shop_name']} ショップ 진단 ---")
            
            if s['platform'] == 'rakuten':
                api_key = s['api_key']
                api_secret = s.get('api_secret', '')
                
                print(f"📡 라쿠텐 API 呼び出し 試行... (Key: {api_key[:5]}*** / Secret: {api_secret[:5]}***)")
                
                rakuten = RakutenRMSClient(service_secret=api_key, license_key=api_secret)
                inquiries = rakuten.get_inquiry_list()
                
                print(f"📊 수집 結果: {len(inquiries)}件의 お問い合わせ를 발견しました.")
                for i in inquiries:
                    print(f"   - [ID: {i.get('rakuten_inquiry_id')}] {i.get('title')[:20]}...")
            else:
                print(f"ℹ️ {s['platform']} プラットフォーム은 現在 진단 대상이 ではありません.")
                
    except Exception as e:
        print(f"❌ 진단 중 치명적 エラーが発生しました: {str(e)}")
    
    print("\n" + "="*50)
    print("✨ [Debug Bot] 진단 終了")
    print("="*50 + "\n")

if __name__ == "__main__":
    asyncio.run(debug_run())
