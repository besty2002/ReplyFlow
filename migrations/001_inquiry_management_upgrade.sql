-- =====================================================
-- ReplyFlow 問い合わせ管理 고도화 DB Migration
-- Supabase SQL Editor에서 실행하세요
-- =====================================================

-- 1. inquiries 테이블 확장
ALTER TABLE inquiries 
  ADD COLUMN IF NOT EXISTS assigned_to UUID,
  ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'normal',
  ADD COLUMN IF NOT EXISTS sentiment VARCHAR(20),
  ADD COLUMN IF NOT EXISTS sentiment_score FLOAT,
  ADD COLUMN IF NOT EXISTS ai_tags TEXT[],
  ADD COLUMN IF NOT EXISTS customer_email VARCHAR(255);

-- 2. 내부 메모 테이블
CREATE TABLE IF NOT EXISTS internal_notes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  inquiry_id UUID NOT NULL REFERENCES inquiries(id) ON DELETE CASCADE,
  company_id UUID NOT NULL,
  author_id UUID NOT NULL,
  author_email VARCHAR(255),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE internal_notes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Company members can manage notes" ON internal_notes;
CREATE POLICY "Company members can manage notes" ON internal_notes
  FOR ALL USING (company_id IN (
    SELECT company_id FROM company_users WHERE user_id = auth.uid()
  ));

CREATE INDEX IF NOT EXISTS idx_internal_notes_inquiry ON internal_notes(inquiry_id);

-- 3. 학습 검증 테이블 (Human-in-the-Loop)
CREATE TABLE IF NOT EXISTS training_reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL,
  training_log_id UUID NOT NULL,
  inquiry_id UUID NOT NULL,
  
  original_question TEXT NOT NULL,
  original_ai_answer TEXT NOT NULL,
  
  corrected_answer TEXT,
  correction_type VARCHAR(30),
  
  original_category VARCHAR(100),
  corrected_category VARCHAR(100),
  original_sentiment VARCHAR(20),
  corrected_sentiment VARCHAR(20),
  
  reviewed_by UUID,
  reviewed_at TIMESTAMPTZ,
  review_note TEXT,
  is_training_ready BOOLEAN DEFAULT FALSE,
  quality_score FLOAT DEFAULT 0,
  
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE training_reviews ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Company members can manage reviews" ON training_reviews;
CREATE POLICY "Company members can manage reviews" ON training_reviews
  FOR ALL USING (company_id IN (
    SELECT company_id FROM company_users WHERE user_id = auth.uid()
  ));

-- 4. ai_training_logs 확장
ALTER TABLE ai_training_logs 
  ADD COLUMN IF NOT EXISTS review_status VARCHAR(20) DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS quality_score FLOAT,
  ADD COLUMN IF NOT EXISTS human_edited_answer TEXT,
  ADD COLUMN IF NOT EXISTS original_ai_answer TEXT;

-- 5. 검색 인덱스
CREATE INDEX IF NOT EXISTS idx_inquiries_customer ON inquiries(customer_id);
CREATE INDEX IF NOT EXISTS idx_inquiries_customer_email ON inquiries(customer_email);
CREATE INDEX IF NOT EXISTS idx_inquiries_status ON inquiries(status);
CREATE INDEX IF NOT EXISTS idx_inquiries_received_at ON inquiries(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_inquiries_assigned_to ON inquiries(assigned_to);
CREATE INDEX IF NOT EXISTS idx_inquiries_priority ON inquiries(priority);
CREATE INDEX IF NOT EXISTS idx_inquiries_sentiment ON inquiries(sentiment);
