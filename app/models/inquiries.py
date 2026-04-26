from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class InquiryCreate(BaseModel):
    title: str = Field(..., description="문의 제목", min_length=1)
    content: str = Field(..., description="문의 내용상세", min_length=5)
    # 초기 테스트 목적이므로 아래 값들은 지정하지 않으면 Mock 데이터 사용
    rakuten_inquiry_id: Optional[str] = "MOCK-123"
    customer_id: Optional[str] = "tester-01"

class InquiryResponse(BaseModel):
    id: str
    company_id: str
    rakuten_inquiry_id: str
    customer_id: Optional[str]
    title: str
    content: str
    status: str
    received_at: datetime
    created_at: datetime
