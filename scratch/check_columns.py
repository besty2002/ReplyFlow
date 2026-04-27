import asyncio
import os
import sys
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.getcwd())

from app.core.config import settings

async def check_schema():
    admin_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SERVICE_ROLE_KEY")
    if not admin_key:
        print("❌ SERVICE_ROLE_KEY not found")
        return
    
    sb = create_client(settings.SUPABASE_URL, admin_key)
    
    tables = ["inquiries", "internal_notes", "training_reviews", "reply_drafts"]
    for table in tables:
        try:
            res = sb.table(table).select("*").limit(1).execute()
            print(f"Table '{table}' exists.")
        except Exception as e:
            print(f"Table '{table}' check failed: {e}")
    
    # Check status values in inquiries
    try:
        res = sb.table("inquiries").select("status").execute()
        statuses = set(item['status'] for item in res.data)
        print(f"Statuses found in inquiries: {statuses}")
    except Exception as e:
        print(f"Status check failed: {e}")

if __name__ == "__main__":
    asyncio.run(check_schema())
