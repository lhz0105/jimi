-- 0002: 触发去重状态（每会话一行）
-- 记录最近一次触发分析的"证据指纹"，用于识别同一诉求被持续消息重复触发。

CREATE TABLE IF NOT EXISTS conversation_trigger_state (
  conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
  last_run_id TEXT,
  last_signature TEXT NOT NULL,
  last_message_seq INTEGER NOT NULL DEFAULT 0,
  last_triggered_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
