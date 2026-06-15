-- =====================================================
-- ReplyFlow sync status tracking
-- Supabase SQL Editor에서 실행하세요
-- =====================================================

CREATE TABLE IF NOT EXISTS sync_status (
  sync_key TEXT PRIMARY KEY,
  status VARCHAR(20) NOT NULL DEFAULT 'idle',
  last_started_at TIMESTAMPTZ,
  last_completed_at TIMESTAMPTZ,
  summary TEXT,
  error_message TEXT,
  inserted_count INTEGER DEFAULT 0,
  deleted_count INTEGER DEFAULT 0,
  unchanged_count INTEGER DEFAULT 0,
  run_source VARCHAR(50),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE sync_status ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Company members can view sync status" ON sync_status;
CREATE POLICY "Company members can view sync status" ON sync_status
  FOR SELECT USING (auth.role() = 'authenticated');

DROP POLICY IF EXISTS "Service role can manage sync status" ON sync_status;
CREATE POLICY "Service role can manage sync status" ON sync_status
  FOR ALL USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

INSERT INTO sync_status (sync_key, status, summary, run_source)
VALUES ('rakuten_reconcile', 'idle', 'まだ同期が実行されていません。', 'bootstrap')
ON CONFLICT (sync_key) DO NOTHING;
