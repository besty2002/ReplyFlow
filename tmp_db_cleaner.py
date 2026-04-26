import httpx
from app.core.config import settings

def clean_db_korean():
    print("🚀 [DB Cleaner] 데이터 정제 시작...")
    
    headers = {
        "apikey": settings.SUPABASE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_KEY}", # 서비스 롤 권한 필요시 KEY 사용
        "Content-Type": "application/json"
    }

    # 1. 숍 이름 정제 (예: '라쿠텐 숍' -> '楽天ショップ')
    shop_url = f"{settings.SUPABASE_URL}/rest/v1/connected_shops"
    with httpx.Client() as client:
        # 모든 숍 가져오기
        resp = client.get(shop_url, headers=headers)
        if resp.status_code == 200:
            shops = resp.json()
            for shop in shops:
                old_name = shop.get("shop_name", "")
                if "라쿠텐" in old_name or "고객 문의" in old_name:
                    new_name = old_name.replace("라쿠텐", "楽天").replace("고객 문의", "問い合わせ")
                    update_url = f"{shop_url}?id=eq.{shop['id']}"
                    client.patch(update_url, headers=headers, json={"shop_name": new_name})
                    print(f"✅ 숍 이름 변경: {old_name} -> {new_name}")

    # 2. 문의 내역 정제 (제목/내용에 '라쿠텐 고객 문의'가 있는 경우)
    inquiry_url = f"{settings.SUPABASE_URL}/rest/v1/inquiries"
    with httpx.Client() as client:
        # 모든 문의 가져오기
        resp = client.get(inquiry_url, headers=headers)
        if resp.status_code == 200:
            inquiries = resp.json()
            for inq in inquiries:
                old_title = inq.get("title", "")
                old_content = inq.get("content", "")
                
                needs_update = False
                update_payload = {}

                if "라쿠텐" in old_title or "고객 문의" in old_title:
                    update_payload["title"] = old_title.replace("라쿠텐", "楽天").replace("고객 문의", "問い合わせ")
                    needs_update = True
                
                if "라쿠텐" in old_content or "고객 문의" in old_content:
                    update_payload["content"] = old_content.replace("라쿠텐", "楽天").replace("고객 문의", "問い合わせ")
                    needs_update = True

                if needs_update:
                    update_inq_url = f"{inquiry_url}?id=eq.{inq['id']}"
                    client.patch(update_inq_url, headers=headers, json=update_payload)
                    print(f"✅ 문의 데이터 정제 완료 (ID: {inq['id']})")

    print("🏁 [DB Cleaner] 모든 정제 작업이 완료되었습니다!")

if __name__ == "__main__":
    clean_db_korean()
