from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class InquiryCreate(BaseModel):
    title: str = Field(..., description="문의 제목", min_length=1)
    content: str = Field(..., description="문의 내용상세", min_length=5)
    # 초기 테스트 목적이므로 아래 값들은 지정하지 않으면 Mock 데이터 사용
    rakuten_inquiry_id: Optional[str] = "MOCK-123"
    customer_id: Optional[str] = "tester-01"

class InquiryUpdate(BaseModel):
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    sentiment: Optional[str] = None

class InternalNoteCreate(BaseModel):
    content: str

class InternalNoteResponse(BaseModel):
    id: str
    inquiry_id: str
    company_id: str
    author_id: str
    content: str
    created_at: datetime
