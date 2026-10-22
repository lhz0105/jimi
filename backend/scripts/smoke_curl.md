# 冒烟验证命令集（curl / PowerShell）

> 服务默认地址 `http://127.0.0.1:8000`；本机回环访问时默认 key 可省略。
> 远程访问需带 `X-API-Key`（外部接口用 EXTERNAL_API_KEY，管理接口用 ADMIN_API_KEY）。

## 0. 健康检查

```bash
curl -s http://127.0.0.1:8000/api/admin/health -H "X-API-Key: change-me-admin"
```

## 1. 对外接口：触发判断（规则引擎，不花 token）

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/analyze/check \
  -H "Content-Type: application/json" \
  -d "{\"inline\":{\"messages\":[{\"role\":\"customer\",\"text\":\"收到的货是碎的，必须退款！\"}],\"images\":[{\"url\":\"https://example.com/broken.jpg\"}]}}"
```

## 2. 演示平台：创建会话 + 上传图片 + 发消息（自动触发判断）

```bash
# 创建会话
curl -s -X POST http://127.0.0.1:8000/api/demo/conversations \
  -H "Content-Type: application/json" \
  -d "{\"customer_name\":\"张三\",\"channel\":\"demo\",\"mode\":\"manual\"}"

# 一键新建演示会话（含占位图片：破损索赔 / 诊断单 / 种草帖）
curl -s -X POST "http://127.0.0.1:8000/api/demo/seed/product_damage_claim"
curl -s -X POST "http://127.0.0.1:8000/api/demo/seed/medical_cert_claim"
curl -s -X POST "http://127.0.0.1:8000/api/demo/seed/seeding_post"

# 上传图片（返回 attachment_id / sha256 / url）
curl -s -X POST "http://127.0.0.1:8000/api/demo/conversations/<CONV_ID>/upload" \
  -F "file=@D:/test/broken.jpg"

# 发客户消息（自动跑规则判断，返回 analysis 提示）
curl -s -X POST "http://127.0.0.1:8000/api/demo/conversations/<CONV_ID>/messages" \
  -H "Content-Type: application/json" \
  -d "{\"role\":\"customer\",\"text\":\"杯子碎了，必须退款！\",\"attachment_ids\":[\"<ATT_ID>\"]}"
```

## 3. 手动启动分析 + 轮询状态

```bash
curl -s -X POST "http://127.0.0.1:8000/api/demo/conversations/<CONV_ID>/trigger-analysis" \
  -H "Content-Type: application/json" -d "{\"trigger_mode\":\"manual\"}"

curl -s "http://127.0.0.1:8000/api/v1/analyze/runs/<RUN_ID>"
```

## 4. 自动链（等待确认 → 确认开始）

```bash
RUN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/analyze/runs \
  -H "Content-Type: application/json" -H "Idempotency-Key: conv123-v1" \
  -d "{\"conversation_id\":\"<CONV_ID>\",\"trigger_mode\":\"auto\",\"auto_confirm\":false}" \
  | python -c "import sys,json;print(json.load(sys.stdin)['run_id'])")

curl -s -X POST "http://127.0.0.1:8000/api/v1/analyze/runs/$RUN/confirm"
```

## 5. SSE 实时观测（另开终端；Ctrl+C 断开）

```bash
curl -N "http://127.0.0.1:8000/api/admin/runs/<RUN_ID>/stream"

# 断线续传（Last-Event-ID 或 from_seq）
curl -N -H "Last-Event-ID: 40" "http://127.0.0.1:8000/api/admin/runs/<RUN_ID>/stream"
curl -N "http://127.0.0.1:8000/api/admin/runs/<RUN_ID>/stream?from_seq=40"
```

## 6. 报告与事件历史

```bash
curl -s "http://127.0.0.1:8000/api/v1/analyze/runs/<RUN_ID>/report?format=json"
curl -s "http://127.0.0.1:8000/api/v1/analyze/runs/<RUN_ID>/report?format=markdown"
curl -s "http://127.0.0.1:8000/api/admin/runs/<RUN_ID>/events?limit=200"
curl -s "http://127.0.0.1:8000/api/admin/runs/<RUN_ID>/tool-calls"
```

## 7. 管理面板：规则 / 知识库 / 统计

```bash
curl -s "http://127.0.0.1:8000/api/admin/rules"
curl -s -X POST "http://127.0.0.1:8000/api/admin/rules/reload"

curl -s "http://127.0.0.1:8000/api/admin/kb/documents"
curl -s "http://127.0.0.1:8000/api/admin/kb/search?q=破损索赔判定标准&top_k=4"
curl -s -X POST "http://127.0.0.1:8000/api/admin/kb/reindex?rebuild=true"

curl -s "http://127.0.0.1:8000/api/admin/stats?days=7"
curl -s "http://127.0.0.1:8000/api/admin/config"
```

## 8. 取消运行（幂等）

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/analyze/runs/<RUN_ID>/cancel"
```
