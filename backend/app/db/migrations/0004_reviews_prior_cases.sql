-- 0004: 人工复核 + 先前案例（检索式自学习）

ALTER TABLE analysis_runs ADD COLUMN review_required INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS run_reviews (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL UNIQUE REFERENCES analysis_runs(id) ON DELETE CASCADE,
  verdict TEXT NOT NULL,                                  -- fraud | genuine | insufficient
  reason TEXT NOT NULL,
  reviewer TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'in_dialogue',             -- pending | in_dialogue | generated
  agent_turns INTEGER NOT NULL DEFAULT 0,
  llm_usage_json TEXT NOT NULL DEFAULT '{}',
  generation_error TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  generated_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_run_reviews_status ON run_reviews(status);

CREATE TABLE IF NOT EXISTS review_messages (
  id TEXT PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES run_reviews(id) ON DELETE CASCADE,
  role TEXT NOT NULL,                                     -- human | agent | system
  content TEXT NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_messages_review ON review_messages(review_id, created_at);

CREATE TABLE IF NOT EXISTS prior_cases (
  id TEXT PRIMARY KEY,
  review_id TEXT UNIQUE REFERENCES run_reviews(id) ON DELETE SET NULL,
  run_id TEXT REFERENCES analysis_runs(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  scenario TEXT NOT NULL DEFAULT '',
  human_verdict TEXT NOT NULL,
  markdown TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  content_hash TEXT NOT NULL DEFAULT '',
  indexed_at INTEGER,
  index_error TEXT,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prior_cases_scenario ON prior_cases(scenario);
