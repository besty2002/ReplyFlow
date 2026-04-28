import asyncio
import os
import sys
from datetime import datetime

# 프로젝트 パス 追加
sys.path.append(os.getcwd())

try:
    from supabase import create_client
    from app.core.config import settings
    from app.core.rakuten_client import RakutenRMSClient
    from app.core.ai_client import ai_client
except ImportError as e:
    print(f"❌ 임포트 エラー: {e}")
    sys.exit(1)

async def force_sync():
    print("\n" + "🚀"*10)
    print("라쿠텐 실時間 お問い合わせ 강제 수집 및 DB 保存 開始!")
    print("🚀"*10 + "\n")

    # 1. DBで 有効化된 라쿠텐 ショップ 取得
    supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    shops = supabase.table("connected_shops").select("*").eq("platform", "rakuten").execute()
    
    if not shops.data:
        print("❌ DB에 登録된 라쿠텐 ショップ이 ありません. 비즈니스 設定で 먼저 登録してください.")
        return

    shop = shops.data[0]
    print(f"✅ 대상 ショップ 발견: {shop['shop_name']}")

    # 2. 라쿠텐 API 呼び出し
    rakuten = RakutenRMSClient(service_secret=shop['api_key'], license_key=shop.get('api_secret', ''))
    inquiries = rakuten.get_inquiry_list()
    
    print(f"📡 라쿠텐 サーバー로から {len(inquiries)}件의 お問い合わせ를 수집しました.")

    for inq in inquiries:
        raw_id = inq["rakuten_inquiry_id"]
        
        # 중복 체크
        exists = supabase.table("inquiries").select("id").eq("rakuten_inquiry_id", raw_id).execute()
        if exists.data:
            print(f"⏩ 이미 수집된 お問い合わせです (ID: {raw_id}). 件너뜁니다.")
            continue

        # DB 保存
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
            print(f"✅ DB 保存 完了: {raw_id} (Internal ID: {inq_id})")
            
            # AI 초안 生成
            print("🤖 AI 返信 生成 중...")
            ai_res = ai_client.generate_reply(new_data["content"])
            
            # 초안 保存
            supabase.table("reply_drafts").insert({
                "company_id": shop["company_id"],
                "inquiry_id": inq_id,
                "ai_suggested_reply": ai_res.get("reply", ""),
                "status": "draft"
            }).execute()
            print("📝 AI 초안 生成 및 保存 完了!")
            
        except Exception as e:
            print(f"❌ 保存 중 エラーが発生しました: {e}")

    print("\n" + "="*50)
    print("✨ 모든 작업이 完了되었します! ダッシュボード를 새로고침하してください.")
    print("="*50 + "\n")

if __name__ == "__main__":
    asyncio.run(force_sync())
