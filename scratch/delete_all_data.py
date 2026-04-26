import httpx
import os
from app.core.config import settings
from dotenv import load_dotenv

def clear_all_inquiries():
    load_dotenv()
    print("[DB Cleanup] Starting deletion with correct UUID filters...")
    
    headers = {
        "apikey": settings.SUPABASE_KEY,
        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_ROLE_KEY') or settings.SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    # 1. reply_drafts 삭제
    draft_url = f"{settings.SUPABASE_URL}/rest/v1/reply_drafts"
    with httpx.Client() as client:
        # id가 null이 아닌 모든 행 삭제
        resp = client.delete(f"{draft_url}?id=not.is.null", headers=headers)
        if resp.status_code in [200, 204]:
            print("Successfully deleted all reply_drafts")
        else:
            print(f"Failed to delete drafts: {resp.text}")

    # 2. inquiries 삭제
    inquiry_url = f"{settings.SUPABASE_URL}/rest/v1/inquiries"
    with httpx.Client() as client:
        resp = client.delete(f"{inquiry_url}?id=not.is.null", headers=headers)
        if resp.status_code in [200, 204]:
            print("Successfully deleted all inquiries")
        else:
            print(f"Failed to delete inquiries: {resp.text}")

    print("[DB Cleanup] Cleanup completed.")

if __name__ == "__main__":
    clear_all_inquiries()
