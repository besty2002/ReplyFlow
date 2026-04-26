import httpx
import sys
import os

# 현재 경로를 PYTHONPATH에 추가
sys.path.append(os.getcwd())

from app.core.config import settings

def update_schema():
    # RPC를 통한 SQL 실행 (Supabase 설정에 따라 rpc('exec_sql') 등이 필요할 수 있음)
    # 여기서는 REST API를 통해 직접적으로는 어렵고, 유저에게 요청하는 것이 가장 안전함.
    # 하지만 시도는 해봅니다.
    print("🚀 DB 스키마 업데이트 시도 중...")
    
    # 일반적인 PostgREST API로는 ALTER TABLE이 불가능합니다.
    # Supabase SQL Editor에서 실행하는 것이 가장 확실합니다.
    sql = """
    ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS order_number VARCHAR(255);
    ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS item_name TEXT;
    ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS item_number VARCHAR(255);
    ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS category VARCHAR(100);
    ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS inquiry_type VARCHAR(100);
    """
    
    print("\n[필독] 아래 SQL을 Supabase SQL Editor에서 실행해주세요:")
    print("-" * 50)
    print(sql)
    print("-" * 50)

if __name__ == "__main__":
    update_schema()
