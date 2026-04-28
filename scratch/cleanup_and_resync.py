"""
DB 초기화 + 미답변 문의만 재동기화 스크립트
기존에 잘못 수집된 527건을 전부 삭제하고, UNICONA 미해결 9건만 다시 수집합니다.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.core.config import settings
from app.core.rakuten_client import RakutenRMSClient
from app.core.ai_client import ai_client
from supabase import create_client
import datetime

async def cleanup_and_resync():
    print("=" * 60)
    print("[1/4] DB 초기화 시작")
    print("=" * 60)
    
    admin_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or settings.SUPABASE_KEY
    supabase = create_client(settings.SUPABASE_URL, admin_key)
    
    # 1. 기존 데이터 삭제 (관련 테이블 순서대로)
    # reply_drafts → send_logs → ai_training_logs → internal_notes → inquiries
    tables_to_clean = [
        "reply_drafts",
        "send_logs",
        "ai_training_logs",
        "internal_notes",
        "inquiries",
    ]
    
    for table in tables_to_clean:
        try:
            # neq 조건으로 전체 삭제 (Supabase는 무조건 삭제 시 조건 필요)
            res = supabase.table(table).delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
            count = len(res.data) if res.data else 0
            print(f"  ✅ {table}: {count}건 삭제 완료")
        except Exception as e:
            print(f"  ⚠️ {table}: 삭제 중 오류 (무시) - {e}")
    
    # 2. 연동된 숍 정보 조회
    print(f"\n{'=' * 60}")
    print("[2/4] 연동된 숍 조회")
    print("=" * 60)
    
    shops_res = supabase.table("connected_shops").select("*").execute()
    shops = shops_res.data
    
    if not shops:
        print("❌ 연동된 숍이 없습니다!")
        return
    
    rakuten_shops = [s for s in shops if s["platform"] == "rakuten"]
    print(f"  Rakuten 숍: {len(rakuten_shops)}개")
    
    # 3. Rakuten API에서 미답변 문의만 수집
    print(f"\n{'=' * 60}")
    print("[3/4] Rakuten API 미답변 문의 수집")
    print("=" * 60)
    
    total_new = 0
    for shop in rakuten_shops:
        print(f"\n  🏪 {shop['shop_name']} 수집 중...")
        
        rakuten = RakutenRMSClient(
            service_secret=shop["api_key"],
            license_key=shop.get("api_secret", "")
        )
        
        fetched = await rakuten.get_inquiry_list()
        print(f"  📦 API에서 {len(fetched)}건 수신")
        
        for ext_inq in fetched:
            raw_id = ext_inq["rakuten_inquiry_id"]
            
            new_data = {
                "company_id": shop.get("company_id"),
                "shop_id": shop.get("id"),
                "rakuten_inquiry_id": raw_id,
                "customer_id": ext_inq.get("customer_id", "Unknown"),
                "title": ext_inq.get("title", "No Title"),
                "content": ext_inq.get("content", ""),
                "received_at": ext_inq.get("received_at", datetime.datetime.utcnow().isoformat()),
                "status": "pending",
                "order_number": ext_inq.get("order_number"),
                "item_name": ext_inq.get("item_name"),
                "item_number": ext_inq.get("item_number"),
                "category": ext_inq.get("category"),
                "inquiry_type": ext_inq.get("type"),
            }
            
            try:
                inq_res = supabase.table("inquiries").insert(new_data).execute()
                if inq_res.data:
                    new_inq_id = inq_res.data[0]["id"]
                    print(f"    ✅ #{raw_id} → DB 저장 완료 (고객: {ext_inq.get('customer_id')})")
                    
                    # AI 초안 생성
                    try:
                        ai_result = await ai_client.generate_reply(
                            inquiry_text=new_data["content"],
                            context=new_data
                        )
                        
                        # 카테고리 업데이트
                        supabase.table("inquiries").update({
                            "category": ai_result.get("category", "その他"),
                            "sentiment": ai_result.get("sentiment"),
                            "sentiment_score": ai_result.get("sentiment_score"),
                            "ai_tags": ai_result.get("tags"),
                            "priority": ai_result.get("priority_suggestion"),
                        }).eq("id", new_inq_id).execute()
                        
                        # 초안 저장
                        supabase.table("reply_drafts").insert({
                            "company_id": shop.get("company_id"),
                            "inquiry_id": new_inq_id,
                            "ai_suggested_reply": ai_result.get("reply", "エラー"),
                            "status": "draft",
                        }).execute()
                        
                        print(f"       🤖 AI 초안 생성 완료 (카테고리: {ai_result.get('category')})")
                    except Exception as e:
                        print(f"       ⚠️ AI 초안 생성 실패 (무시): {e}")
                    
                    total_new += 1
                else:
                    print(f"    ❌ #{raw_id} → DB 저장 실패")
            except Exception as e:
                print(f"    ❌ #{raw_id} → 오류: {e}")
    
    # 4. 결과 확인
    print(f"\n{'=' * 60}")
    print(f"[4/4] 완료! 총 {total_new}건의 미답변 문의 수집 완료")
    print("=" * 60)
    
    # DB 최종 확인
    final = supabase.table("inquiries").select("id, rakuten_inquiry_id, customer_id, status, received_at").order("received_at", desc=True).execute()
    if final.data:
        print(f"\n  📋 현재 DB 문의 목록 ({len(final.data)}건):")
        for inq in final.data:
            print(f"    [{inq['status']}] {inq['rakuten_inquiry_id']} | {inq['customer_id']} | {inq.get('received_at', '')[:16]}")

if __name__ == "__main__":
    asyncio.run(cleanup_and_resync())
