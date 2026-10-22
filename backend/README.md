# 迹觅·Evidence — 后端服务

高可观测多 Agent 后端：识别客服退款欺诈（AI 伪造图片/诊断单、陈述矛盾）与种草内容真伪（真实分享 vs 商单营销）。
所有接口可用 curl / Swagger 独立验证；配套两个前端：

- **管理观测台** `../frontend/`（Vue 3，对接 `/api/admin`，深色运维台）；
- **模拟客服平台** `../demo_platform/`（独立前端 + 独立后端 + SQLite，白底 + 少量紫色，只通过对外接口 `/api/v1/analyze/*` 接入）；
- 演示客服平台后端还会把 **SSE 事件流原样代理**给它的前端，用于展示"真实接入"的写法。

## 模拟客服平台（demo_platform）

```bash
cd ../demo_platform/backend && .venv\Scripts\python.exe run.py    # :8001
cd ../demo_platform/frontend && npm run dev                        # :5174
```

发消息 → agent 规则判断（含语义相似度）→ 平台提示"开始分析" → 确认后实时展示思考/工具调用/知识库命中 → 报告与证据链。
详见 `../demo_platform/README.md`；接入要点见其中「inline 图片只传 URL」等说明。

## 管理观测台（前端）

```bash
cd ../frontend
npm install
npm run dev        # http://localhost:5173（Vite 代理 /api 到本后端，无需处理跨域）
```

功能：运行实时事件流（输入/思考/工具调用/RAG 命中，SSE 断线续传）、报告与证据链、工具调用明细、
知识库管理与检索调试（三路分数）、规则 YAML 编辑、统计与系统健康。详见 `frontend/README.md`。

跨域：后端已内置 `CORSMiddleware`，白名单由 `.env` 的 `CORS_ORIGINS` 控制（默认含 5173/4173 本地端口）；
前端独立部署时用 `VITE_API_BASE=http://<后端地址>` 构建即可直连。

## 快速开始

```bash
cd backend

# 1) 虚拟环境 + 依赖（Windows，建议先跑一次）
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
# 国内网络可加镜像：-i https://mirrors.aliyun.com/pypi/simple/

# 2) 配置（填入你的网关 base_url / key；或先 LLM_MODE=fake 无 key 跑通全链路）
copy .env.example .env

# 3)（可选）预热本地向量模型 + 导入示例知识库
.venv\Scripts\python.exe scripts\download_models.py
#    若下载不稳（代理/镜像问题），改用 curl 手动下载（断点续传、更可靠）：
#    .venv\Scripts\python.exe scripts\fetch_model_files.py
.venv\Scripts\python.exe scripts\ingest_kb.py

# 4) 启动（管理面板接口 + 演示平台接口 + agent 服务，单 worker）
.venv\Scripts\python.exe scripts\run_server.py

# 打开 http://127.0.0.1:8000/docs 查看全部接口
```

## 三组接口

| 分组 | 前缀 | 用途 |
|---|---|---|
| 对外分析 | `/api/v1/analyze` | 供外部客服平台接入：`/check`（规则判断，零 token）、`/runs`（启动/确认/取消/状态/报告/事件/SSE） |
| 演示客服平台 | `/api/demo` | 会话/消息/图片上传/一键演示剧本/人工触发分析 |
| 管理面板 | `/api/admin` | 运行观测、SSE 事件流、工具调用清单、规则管理、知识库管理、统计、健康检查 |

鉴权：`X-API-Key`（外部 `EXTERNAL_API_KEY`，管理 `ADMIN_API_KEY`）。未配置（默认值）时仅允许本机回环访问。
详细命令见 `scripts/smoke_curl.md`。

外部平台启动运行时可在 `POST /api/v1/analyze/runs` 携带
`external_ref: {source, conversation_id, customer_name}`：仅用于观测台展示与追溯（不参与分析），
观测台会把它显示在运行 ID 下方，便于把外部会话与运行对应起来。

## 执行链

- **自动链**：客户消息 → 规则引擎判断（关键词 + 语义 + 图片 + 渠道，零 LLM 成本）→ 需要分析则返回提示（`awaiting_confirm`）→ 前端确认 → 拉取对话上下文 → agent loop → 报告。
- **手动链**：前端人工启动 → agent loop → 报告。

### 触发判断：5 条消息窗口 + 语义通道

客服对话里**图片与文字常常分开发送**，因此触发判断以"窗口"为单位（`TRIGGER_WINDOW_MESSAGES`，默认 5 条）：

1. **文本先行**：先在窗口文本上判定意图（关键词/正则 + 语义相似度）→ 命中后再在**同一窗口内**取图作为证据；
2. **图片先行**：图片本身不含文本意图，回看窗口内最近 5 条文本是否有退款/破损等诉求；
3. 两种顺序只要落在同一窗口即视为同一诉求的连贯表达，均可触发。窗口外的旧图不参与本次判定（不会重复烧钱）。

**两条判定通道**（`app/rules/rules.yaml`）：

| 通道 | 实现 | 特点 |
|---|---|---|
| 关键词/正则/同义词 | 归一化后精确匹配 | 零成本、可解释；同义词表把"退我钱"归一到"退款" |
| **语义相似度** | 复用本地 BGE 向量模型：锚点短语按文档编码，客户原文按标点切子句后按查询编码，取 max(子句×锚点) 余弦 | 捕捉"没说到'退款'二字但意图相同"的说法（如"这个钱我不要了，你们看着办"）；阈值经真实模型标定（全局 0.68，分组覆盖），模型不可用时自动退回纯关键词 |

- 语义命中随决策一起返回：`CheckResponse.semantic_status`（matched / no_match / disabled / unavailable）与 `semantic_hits`（锚点 → 相似度），管理台运行详情显示为徽章；`/api/admin/health` 的 `rules.semantic.mode` 可查通道状态。
- 触发窗口信息（`window_size / window_oldest_seq / window_newest_seq / image_attachment_ids`）写入运行 `input_snapshot`，agent 只用这批窗口内图片。

### 触发去重：同一诉求不重复烧钱

滑动窗口 + 持续消息会让同一诉求反复命中（客户补图、追问"在吗"都会重新进入窗口）。`app/services/trigger_service.py` 做两层防护：

| 机制 | 规则 | 效果 |
|---|---|---|
| **证据指纹** | 指纹 = 命中规则 + 命中细节（去掉相似度分数）+ 窗口图片 sha256 集合 + 场景 | 同一诉求（同规则、同图片）指纹不变 |
| 无新增客户消息 | 指纹相同且窗口内没有新的客户消息（只有客服回复/系统消息） | **永不重复**（客服续聊不触发） |
| 冷却期 | 指纹相同但客户又发了消息，且距上次触发 < `TRIGGER_DEDUP_TTL_MINUTES`（默认 30 分钟） | 不重复；超过冷却期才允许"同一诉求再次分析" |
| 证据变化 | 补图/换图 → 图片集合变化；新增关键词或语义锚点 → 命中细节变化 | **指纹变化 → 允许补充分析**（如先文字中危、补图后高危） |
| **活跃运行守卫** | 同会话已有 queued / awaiting_confirm / running 的运行 | **直接复用**该运行（手动触发同样不并发）；上次运行失败时允许重试 |

- 手动启动（`/api/demo/.../trigger-analysis`、`/api/v1/analyze/runs` 且 `trigger_mode=manual`）是显式请求：跳过指纹去重，但仍受活跃运行守卫约束；窗口内诉求已滑出时，演示端会回退到该会话最近一次运行的场景。
- 去重结果随提示返回：`analysis.trigger = {action: start|reuse|skip, reason, signature, run_id}`，`run_id` 始终指向关联运行（跳转查看）。
- 状态存于 `conversation_trigger_state` 表（迁移 `0002_trigger_state.sql`）。

## 人工判决与先前案例（检索式自学习）

- **复核资格**：运行结论为 `suspicious` / `fake_claim`，或 `recommended_actions` 含 `manual_review`；`finalize` 时写入 `analysis_runs.review_required`，历史运行启动时回填。
- **管理台**：运行详情新增「人工判决」页签；人工选择 欺诈 / 真实 / 证据不足，填写理由与复核人；Agent 最多追问 4 轮，人工可随时强制生成。
- **案例文档**：包含案件定义、案件细节、判决原因、关键证据、适用边界；写入 `prior_cases` 并进入独立索引。
- **先前案例检索**：独立 Chroma 集合 `prior_case_chunks` + 独立 BM25；图新增 `prior_case_recall` 节点，事件 `rag_hit.source=prior_cases`，证据 `tool=prior_case_recall`。先例仅作参照，**不自动修改规则/阈值**。
- **先例反馈加权（L2）**：仅对本案例裁决 `evidence_refs` 明确引用的先例，在复核完成后由 Agent 按人工判决意图推断 `adopted / overturned / not_applicable / neutral`（置信度 <0.6 记中性）；采纳/推翻分别 +1α/+1β，可靠性 `α/(α+β)`，参与检索排序与证据权重；权重历史可在「先前案例」详情查看。
- **接口**：`/api/admin/runs/{id}/review`（GET/POST）、`/review/messages`、`/review/generate`、`POST /review/stream`（SSE，追问与案例文档逐 token 输出）、`/api/admin/prior-cases*`、`DELETE /prior-cases/{id}`（删除案例并清理索引，来源复核回到可重新生成）、`/prior-cases/{id}/feedback`。
- **配置**：`PRIOR_CASE_ENABLED` / `PRIOR_CASE_TOP_K` / `PRIOR_CASE_COLLECTION`。
- **计费**：DeepSeek Flash 按谷值（CNY/1K：缓存未命中输入 0.001、命中 0.00002、输出 0.004）；usage 中的 cache_read 单独计价。

## Agent 流水线（LangGraph）

```
prepare_case → route_scenario → local_forensics → ai_image_detection（Sightengine）
    → rag_recall → prior_case_recall → vision_analysis（Qwen 定位篡改 + 诉求相关性）
    → investigate（ReAct 工具子代理）→ consistency → adjudicate
        ├─ 证据不足且预算/轮数允许 → 回 investigate
        └─ 完成 → report（零 LLM 模板渲染）→ finalize
```

- **证据链**：每条证据含 `evidence_id / category / source / tool / finding / direction / weight / raw_ref`，生成即发 `evidence` 事件，报告与 SSE 双通道一致。
- **低危判定落实**：识图提示词强制分区输出；仅"产品主体区域"的 AIGC 计 `supports_fake`，人像/背景等与诉求无关区域的 AIGC 记为 `neutral` 并注明不计入风险。Sightengine 高分只作线索，必须由识图模型定位篡改位置并判断与诉求的关系后才能定罪。
- **工具**：`vision_analyze`（结果持久缓存，同图同提示词跨运行复用）、`lookup_kb`（混合检索）、`web_search`（Tavily）、`find_similar_claim_images`（pHash 复用检测）、`get_customer_statements`、`read_file`/`write_file`（沙箱于 `data/workspace/<run_id>/`）。
- **图片重复排查开关**：`IMAGE_DUPLICATE_CHECK_ENABLED=false` 时，`local_forensics` 不再做历史图库比对（不产生 `duplicate_image` 证据），且不注册 `find_similar_claim_images` 工具；EXIF 检查与 pHash 入库仍保留，便于随时恢复。
- 工具统一经预算闸门包装（`app/agent/tools/registry.py::_guarded`）：限次 → 事件 → 落库 → 截断（800 字入 prompt，完整结果留 DB）。
- **第三方预检与视觉定位**：所有图片先调用 Sightengine `models=genai`。`SIGHTENGINE_AI_THRESHOLD=0.90` 是考量阈值：<0.90 不纳入 AI 生成判断，仅记录；≥0.90 才把分数作为“定位线索”注入识图提示。`SIGHTENGINE_CONSTRAINT_THRESHOLD=0.95` 是裁决约束阈值：≥0.95 时最终不得 `likely_genuine` 或 `inconclusive`，至少 `suspicious`。Qwen 输出 `tamper_relation_to_claim`（related/unrelated/uncertain）与 `tamper_location_summary`：related 生成 `supports_fake`；unrelated 且诉求区域真实时，0.90–0.95 生成 `supports_genuine`，≥0.95 生成 `unknown`；uncertain 生成 `unknown`（≥0.95 附硬约束说明）。检测结果按图缓存；医疗单据同样先预检，但只有关键字段被编辑才计入索赔风险。

## 可观测（SSE 事件协议）

信封：`{v, run_id, seq, ts, type, node, level, payload}`；`seq` 运行内单调递增；SSE `id`=seq，支持 `Last-Event-ID` 断线续传。

事件类型：`run_queued / run_awaiting_confirm / run_confirmed / run_start / node_start / node_end / thought / llm_call / llm_result / tool_call / tool_result / tool_error / rag_hit / evidence / verdict / report / budget_warning / warning / error / run_end`。

写入保证：**先落库再发布**（`app/observability/emitter.py`）；SSE 连接先订阅后回放 DB，再按 seq 去重续发（`app/api/stream.py`）。
EventBus 为进程内 pub/sub，服务必须单 worker（`scripts/run_server.py` 已固定）。

## RAG

- 本地向量模型 `BAAI/bge-small-zh-v1.5`（fastembed / ONNX 推理，CPU，免 torch），持久化于 Chroma；BM25（jieba 分词）内存索引；RRF 融合（`k=60, w_dense=1.0, w_bm25=0.8`）。
- 优雅降级：向量模型或 Chroma 不可用 → 自动切 `bm25_only`（`/api/admin/health` 可见 `rag.mode`），服务不因 RAG 挂起。
- 知识库内容：`kb_seed/`（仓库内示例，首次启动拷贝到 `data/kb/`）；可用管理接口上传/删除/重建；检索调试入口 `GET /api/admin/kb/search`（返回 dense/bm25/融合三路分数）。

> **国内网络提示**：模型首次下载约 95MB。若本机开了代理（如 Clash），走代理下载 hf-mirror 反而很慢/易卡死（实测 88KB/s vs 直连 1MB/s），建议直连：
> ```bash
> # bash
> NO_PROXY=hf-mirror.com no_proxy=hf-mirror.com .venv/Scripts/python.exe scripts/download_models.py
> # PowerShell
> $env:NO_PROXY="hf-mirror.com"; .venv\Scripts\python.exe scripts\download_models.py
> ```
> 中断可重跑（支持断点续传）；服务后台初始化，模型就绪前检索返回空结果，不影响启动。

## 成本压缩

规则判断零 LLM ② 识图持久缓存（跨运行复用，命中不计费）③ investigate 只传 digest + 证据摘要 + 未决问题 ④ 工具结果 800 字截断 ⑤ 预算闸门（LLM/工具/识图/联网/成本/轮数上限，超限即收口出"证据不足"结论）⑥ 报告零 LLM 模板渲染 ⑦ `stream_usage` 按节点归因成本（报告与 `/api/admin/stats` 可见）。

## 测试

```bash
.venv\Scripts\python.exe -m pytest            # 全部 mock LLM，无需 key
.venv\Scripts\python.exe -m pytest tests/graph -v
```

覆盖：规则引擎边界、沙箱逃逸拒绝、中文分块、RRF 融合、事件 seq/先落库后发布、预算收口、证据去重、三场景全链路（fake LLM）、识图缓存命中、确认链、取消幂等、Idempotency-Key。

## 配置要点（`.env`）

- `LLM_MODE=real|fake`：`fake` 无需任何 key 即可跑通全链路（用于演示/测试）。
- 网关：`LLM_MAIN_BASE_URL/API_KEY/MODEL`（默认 `deepseek-v4-flash`）、`LLM_VISION_*`（默认 `qwen3.7-flash`）、`TAVILY_API_KEY`。
- `KB_ENABLED=true|false`：关闭后不加载向量模型（无 RAG，服务启动更快；接口返回 `rag.mode=uninitialized`）。
- `HF_ENDPOINT`（默认 `https://hf-mirror.com`）用于向量模型下载；模型文件就绪于 `EMBEDDING_CACHE_DIR/<模型简称>/` 时**自动离线加载**（适合无外网部署）。
- 预算：`BUDGET_MAX_LLM_CALLS/TOOL_CALLS/VISION_CALLS/TAVILY_CALLS/RUN_COST`、`MAX_INVESTIGATE_LOOPS`。
- 数据目录：`data/`（SQLite / uploads / workspace 沙箱 / chroma / reports / models）。

## 目录结构

```
app/
├─ api/            对外(analyze) / 演示(demo) / 管理(admin) 三组路由 + SSE(stream) + schemas
├─ agent/          LangGraph 图、节点(nodes/)、工具(tools/)、提示词(prompts/)、预算/证据/运行器
├─ core/           通用工具（ids/errors/text/files/clock）
├─ db/             SQLite（WAL + 单写锁）、迁移、repositories
├─ llm/            网关工厂、reasoning_content 兼容、fake 模型、识图封装、价格表
├─ observability/  事件协议、总线、emitter、回调和节点装饰器
├─ rag/            embedder/chunker/store(chroma)/bm25/retriever(RRF)/ingest
├─ rules/          规则引擎（rules.yaml 可热重载）+ 触发判断
└─ services/       装配(bootstrap)、演示平台、知识库服务、决策缓存
```

## 已知取舍

- 向量模型用 **fastembed（ONNX）** 替代 sentence-transformers：同等本地 CPU 中文向量能力，免 200MB+ torch 依赖，Windows/国内网络安装更稳（`.env` 的 `EMBEDDING_MODEL` 可换）。
- 工具预算/事件/持久化通过**工具包装层**实现（而非 LangChain middleware），减少对框架中间件 API 版本的耦合。
- 报告中的 `thought_timeline` 由运行事件（thought/tool/rag_hit）生成，默认每步一条而非 token 级流（可观测与成本的折中）。
