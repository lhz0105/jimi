-- 0001_init: 全量初始 schema（会话/消息/附件/运行/事件/报告/图片指纹/视觉缓存/知识库）

CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  customer_name TEXT NOT NULL DEFAULT '',
  channel TEXT NOT NULL DEFAULT 'demo',
  mode TEXT NOT NULL DEFAULT 'manual',            -- auto | manual | off
  meta TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  role TEXT NOT NULL,                              -- customer | agent | system
  content TEXT NOT NULL DEFAULT '',
  content_type TEXT NOT NULL DEFAULT 'text',
  meta TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL,
  UNIQUE(conversation_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, seq);

CREATE TABLE IF NOT EXISTS attachments (
  id TEXT PRIMARY KEY,
  message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
  conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,  -- 内联载荷场景可为 NULL
  sha256 TEXT NOT NULL,
  mime TEXT NOT NULL DEFAULT 'application/octet-stream',
  path TEXT NOT NULL,
  width INTEGER,
  height INTEGER,
  bytes INTEGER,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attachments_sha ON attachments(sha256);
CREATE INDEX IF NOT EXISTS idx_attachments_conv ON attachments(conversation_id);

CREATE TABLE IF NOT EXISTS analysis_runs (
  id TEXT PRIMARY KEY,
  conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
  scenario TEXT NOT NULL DEFAULT 'generic',
  trigger_mode TEXT NOT NULL DEFAULT 'manual',
  status TEXT NOT NULL DEFAULT 'queued',           -- queued | awaiting_confirm | running | succeeded | failed | cancelled
  rules_decision TEXT NOT NULL DEFAULT '{}',
  input_snapshot TEXT NOT NULL DEFAULT '{}',
  verdict TEXT,
  risk_level TEXT,
  confidence REAL,
  error TEXT,
  cost_json TEXT NOT NULL DEFAULT '{}',
  progress_json TEXT NOT NULL DEFAULT '{}',
  idempotency_key TEXT UNIQUE,
  callback_url TEXT,
  created_at INTEGER NOT NULL,
  started_at INTEGER,
  finished_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_runs_status ON analysis_runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_conv ON analysis_runs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_runs_created ON analysis_runs(created_at DESC);

CREATE TABLE IF NOT EXISTS run_confirmations (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  decision TEXT NOT NULL,                          -- confirm | cancel
  decided_by TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_confirmations_run ON run_confirmations(run_id);

CREATE TABLE IF NOT EXISTS run_events (
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  ts INTEGER NOT NULL,
  type TEXT NOT NULL,
  node TEXT,
  level TEXT NOT NULL DEFAULT 'info',
  payload TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_run_ts ON run_events(run_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_type ON run_events(type);

CREATE TABLE IF NOT EXISTS tool_calls (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  tool TEXT NOT NULL,
  args_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT,
  result_ref TEXT,
  status TEXT NOT NULL DEFAULT 'ok',
  latency_ms INTEGER,
  cost_json TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_toolcalls_run ON tool_calls(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_toolcalls_tool ON tool_calls(tool);

CREATE TABLE IF NOT EXISTS reports (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL UNIQUE REFERENCES analysis_runs(id) ON DELETE CASCADE,
  json TEXT NOT NULL,
  markdown TEXT NOT NULL DEFAULT '',
  version TEXT NOT NULL DEFAULT 'v1',
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS image_hashes (
  sha256 TEXT PRIMARY KEY,
  phash TEXT,
  dhash TEXT,
  ahash TEXT,
  width INTEGER,
  height INTEGER,
  mime TEXT,
  exif_json TEXT,
  first_run_id TEXT,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_image_hashes_phash ON image_hashes(phash);

CREATE TABLE IF NOT EXISTS vision_cache (
  sha256 TEXT NOT NULL,
  prompt_hash TEXT NOT NULL,
  model TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (sha256, prompt_hash, model)
);

CREATE TABLE IF NOT EXISTS kb_documents (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL DEFAULT '',
  scenario TEXT NOT NULL DEFAULT 'generic',
  doc_type TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '[]',
  content_hash TEXT NOT NULL DEFAULT '',
  chunk_count INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kbdoc_scenario ON kb_documents(scenario);

CREATE TABLE IF NOT EXISTS kb_chunks (
  id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  text TEXT NOT NULL,
  heading_path TEXT NOT NULL DEFAULT '',
  scenario TEXT NOT NULL DEFAULT 'generic',
  meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_kbchunks_doc ON kb_chunks(doc_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_kbchunks_scenario ON kb_chunks(scenario);

CREATE TABLE IF NOT EXISTS kb_index_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  kb_version TEXT NOT NULL DEFAULT '',
  bm25_chunks INTEGER NOT NULL DEFAULT 0,
  dense_chunks INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL
);
