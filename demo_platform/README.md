# 迹觅·Evidence 客服演示台（模拟客服平台）

用于演示「已有客服平台接入 Agent 分析服务」的完整流程。**独立的前端、后端与数据库**，
与 agent 服务仅通过其对外接口 `/api/v1/analyze/*` 交互（不依赖任何管理接口）。

```
demo_platform/
├─ backend/     独立 FastAPI 服务（端口 8001），SQLite，负责会话/图片存储与 agent 客户端
│  ├─ app/agent_client.py   只使用 /check、/runs、/confirm、/runs/{id}、/report、/stream
│  ├─ app/service.py        inline 载荷组装（最近 8 条消息 + 最近 5 条消息内的图片 URL）
│  └─ app/api.py            对演示前端的 API + SSE 原样代理
└─ frontend/    Vue 3 + Vite + TS + Tailwind（端口 5174），白底 + 少量紫色
```

## 启动

```bash
# 1) agent 服务（端口 8000）需先运行
cd ../backend && .venv/Scripts/python.exe scripts/run_server.py

# 2) 演示平台后端（独立 venv）
cd ../demo_platform/backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
.venv/Scripts/python.exe run.py            # http://127.0.0.1:8001/docs

# 3) 演示平台前端
cd ../frontend
npm install
npm run dev                                # http://localhost:5174
```

配置见 `backend/.env.example`（默认值即可与本地 agent 联调；对外接口鉴权用 `AGENT_API_KEY`，
默认 `change-me-ext` 与 agent 的 `EXTERNAL_API_KEY` 一致）。

## 演示流程（与 agent 的自动执行链一一对应）

1. 左上「演示剧本」载入场景（AI 破损图索赔 / 诊断单矛盾 / 种草帖），或「新建」会话后手动发消息/传图；
2. 客户消息发出 → 平台后端调用 `POST /api/v1/analyze/check`（inline：最近消息 + 图片 URL）→ 返回是否需分析；
3. 命中规则 → 右侧出现「检测到疑似欺诈场景 → 开始分析」卡片（含场景、风险、命中规则、语义命中）；
4. 点击「开始分析」→ 平台调用 `POST /api/v1/analyze/runs`；若 agent 返回待确认（规则要求人工确认），
   平台代为 `confirm`（点击本身即人工确认）；
5. 平台通过 `/api/analyses/{id}/stream` **原样代理 agent 的 SSE**，右侧实时展示思考过程、工具调用、知识库命中、证据；
6. 完成后展示结论（风险/置信度/摘要/建议动作）、证据链，并可查看 Markdown/JSON 报告与导出。

**接入要点**：
- inline 图片只传 `url`（平台把图片存在自己的存储并对外提供 `/files/{sha}.png`，agent 按 URL 拉取）；
  不要传 `sha256`（那是"引用 agent 自己库里的附件"的语义）。
- 平台侧的去重/去重提示：agent 对同一诉求（同规则+同图片指纹）在冷却期内返回既有运行，
  平台检测到 `run_id` 已存在时直接展示既有分析（toast 提示"近期已分析过"）。
- `GET /api/analyses/{id}` 每次都向 agent 同步权威状态（平台本地只存关联关系与快照）。
- 启动分析时传 `external_ref`（来源、平台会话 ID、客户名）：agent 会把它记入运行，
  观测台的运行列表与总览会显示"演示台 · 客户名 · conv_xxx"，便于把演示会话与运行对应起来。
- **每条客户消息都会判定**：手动发送的消息即时调用 `/check`；**演示剧本灌入时逐条判定**（只判断、不启动分析，
  零 LLM 成本），因此剧本里的每条客户消息都会显示"规则命中"提示。旧版本灌入的会话在打开时自动补算
  （`POST /api/conversations/{id}/recheck`，`?force=true` 可全量重算）。

## 演示平台自己的 API（面向前端）

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/conversations`、`GET /api/conversations`、`GET /api/conversations/{id}` | 会话与详情（消息/图片/分析） |
| POST | `/api/conversations/{id}/messages` | 发消息；客户消息自动调用 agent `/check` |
| POST | `/api/conversations/{id}/upload` | 上传图片（存本地，返回可被 agent 拉取的 URL） |
| POST | `/api/conversations/{id}/analyze` | 启动分析（调用 agent `/runs`，必要时代为确认） |
| GET | `/api/analyses/{id}` | 同步并返回分析状态 |
| GET | `/api/analyses/{id}/stream` | SSE 代理（含断线续传） |
| GET | `/api/analyses/{id}/report?format=json\|markdown` | 报告 |
| POST | `/api/analyses/{id}/confirm`、`/cancel` | 确认 / 取消 |
| POST | `/api/demo/seed/{scenario}`、`/api/conversations/{id}/seed/{scenario}` | 演示剧本（逐条客户消息调用 `/check`，不自动分析） |
| POST | `/api/conversations/{id}/recheck?force=false` | 补齐/重算消息的触发判断结果 |
| GET | `/files/{sha}.png` | 图片文件服务 |

## 技术选型说明

- 后端选 **Python/FastAPI**：与 agent 同生态，httpx 的流式能力可直接做 SSE 透传；
  Go 在本地演示场景下没有收益（多一套构建与部署），且与现有运维脚本不一致。
- 数据库用 **SQLite**（`data/demo.db`）：会话/消息/图片/分析关联足够，单文件便于演示与重置。
- 前端 **Vue 3 + Vite + TS + Tailwind**，视觉为「白 + 少量紫色」（主操作/选中态用紫，其余白底与浅灰）。
