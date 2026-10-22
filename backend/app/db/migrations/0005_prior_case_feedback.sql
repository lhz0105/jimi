-- 0005: 先前案例反馈加权（Beta 后验）

ALTER TABLE prior_cases ADD COLUMN alpha REAL NOT NULL DEFAULT 2.0;
ALTER TABLE prior_cases ADD COLUMN beta REAL NOT NULL DEFAULT 2.0;
ALTER TABLE prior_cases ADD COLUMN adopted_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE prior_cases ADD COLUMN overturned_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE prior_cases ADD COLUMN feedback_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE prior_cases ADD COLUMN last_feedback_at INTEGER;

CREATE TABLE IF NOT EXISTS prior_case_feedback (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES prior_cases(id) ON DELETE CASCADE,
  run_id TEXT,
  review_id TEXT,
  signal TEXT NOT NULL,                              -- adopted | overturned | not_applicable | neutral
  source TEXT NOT NULL DEFAULT 'agent_inferred',
  confidence REAL,
  weight_before REAL,
  weight_after REAL,
  rationale TEXT NOT NULL DEFAULT '',
  evidence_ids_json TEXT NOT NULL DEFAULT '[]',
  created_at INTEGER NOT NULL,
  UNIQUE(review_id, case_id)
);
CREATE INDEX IF NOT EXISTS idx_prior_feedback_case ON prior_case_feedback(case_id, created_at);
