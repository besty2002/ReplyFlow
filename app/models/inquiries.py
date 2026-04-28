from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class InquiryCreate(BaseModel):
    title: str = Field(..., description="お問い合わせ タイトル", min_length=1)
    content: str = Field(..., description="お問い合わせ内容詳細", min_length=5)
    # 초기 テスト 목적이므로 아래 値들은 지정하지 않으면 Mock データ 使用
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
