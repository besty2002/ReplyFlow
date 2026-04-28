import httpx
from app.core.config import settings

def clean_db_korean():
    print("🚀 [DB Cleaner] データ 정제 開始...")
    
    headers = {
        "apikey": settings.SUPABASE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_KEY}", # サービスロール 権限 필요시 KEY 使用
        "Content-Type": "application/json"
    }

    # 1. ショップ 名前 정제 (예: '라쿠텐 ショップ' -> '楽天ショップ')
    shop_url = f"{settings.SUPABASE_URL}/rest/v1/connected_shops"
    with httpx.Client() as client:
        # すべてのショップ 取得
        resp = client.get(shop_url, headers=headers)
        if resp.status_code == 200:
            shops = resp.json()
            for shop in shops:
                old_name = shop.get("shop_name", "")
                if "라쿠텐" in old_name or "お客様のお問い合わせ" in old_name:
                    new_name = old_name.replace("라쿠텐", "楽天").replace("お客様のお問い合わせ", "問い合わせ")
                    update_url = f"{shop_url}?id=eq.{shop['id']}"
                    client.patch(update_url, headers=headers, json={"shop_name": new_name})
                    print(f"✅ ショップ 名前 変更: {old_name} -> {new_name}")

    # 2. お問い合わせ 내역 정제 (タイトル/内容에 '라쿠텐 お客様のお問い合わせ'가 있는 경우)
    inquiry_url = f"{settings.SUPABASE_URL}/rest/v1/inquiries"
    with httpx.Client() as client:
        # 모든 お問い合わせ 取得
        resp = client.get(inquiry_url, headers=headers)
        if resp.status_code == 200:
            inquiries = resp.json()
            for inq in inquiries:
                old_title = inq.get("title", "")
                old_content = inq.get("content", "")
                
                needs_update = False
                update_payload = {}

                if "라쿠텐" in old_title or "お客様のお問い合わせ" in old_title:
                    update_payload["title"] = old_title.replace("라쿠텐", "楽天").replace("お客様のお問い合わせ", "問い合わせ")
                    needs_update = True
                
                if "라쿠텐" in old_content or "お客様のお問い合わせ" in old_content:
                    update_payload["content"] = old_content.replace("라쿠텐", "楽天").replace("お客様のお問い合わせ", "問い合わせ")
                    needs_update = True

                if needs_update:
                    update_inq_url = f"{inquiry_url}?id=eq.{inq['id']}"
                    client.patch(update_inq_url, headers=headers, json=update_payload)
                    print(f"✅ お問い合わせ データ 정제 完了 (ID: {inq['id']})")

    print("🏁 [DB Cleaner] 모든 정제 작업이 完了되었します!")

if __name__ == "__main__":
    clean_db_korean()
