-- 0003: 外部平台来源标识（演示台等经 /api/v1/analyze 接入的运行）
-- 形如 {"source":"demo_platform","conversation_id":"conv_xxx","customer_name":"客户 10"}
ALTER TABLE analysis_runs ADD COLUMN external_ref_json TEXT;
