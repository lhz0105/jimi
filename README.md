# 迹觅·Evidence

> 让 AI 造假留下证据。面向电商客服与内容平台的反 AIGC 欺诈多智能体系统。

**迹觅·Evidence** 识别 AI 伪造的商品破损图、医疗诊断单和种草内容，输出可解释的证据链、风险结论与人工复核入口。系统把「零 token 触发、多阶段 Agent、多源取证、人工在环、检索式案例记忆」串成一条可观测的闭环。

**核心关键词：** 多链路 · 自学习（检索式） · 人工辅助 · 高可观测 · 成本可控

---

## 为什么做这个项目

生成式模型让造假成本急剧下降：

- 一张 AI 生成的「商品破损图」几分钟就能做出来；
- 诊断单、病历、印章可以被局部替换或拼接；
- 种草帖可以用 AI 配图 + 模板化文案批量生产。

单模型看图不可靠：视觉模型只能判断可见痕迹，对不可见水印、模型指纹、跨案复用图无能为力；人工复核又常常是黑箱，经验留在个人手里。  
迹觅·Evidence 的目标不是「让 AI 替代人」，而是让**每一条判断都有证据、每一次人工判断都能沉淀**。

---

## 核心能力

| 能力 | 说明 |
|---|---|
| **零 token 触发** | 规则/关键词 + BGE 锚点语义余弦，先判断是否需要分析；触发阶段不调用 LLM |
| **多阶段 Agent** | LangGraph 显式流水线：取证 → AI 预检 → 检索 → 视觉定位 → 调查 → 一致性 → 裁决 → 报告 |
| **多源证据链** | EXIF/指纹、知识库、先前案例、视觉定位、第三方检测、联网事实、会话矛盾，每条证据都有来源、方向、权重和 `evidence_id` |
| **AI 生成预检 + 定位** | Sightengine 先检测不可见水印；Qwen 再定位篡改区域，并判断与客户诉求的关系，避免「高分直接定罪」 |
| **混合 RAG** | BGE 向量 + jieba BM25 + RRF；知识库与先前案例使用独立索引，互不污染 |
| **人工在环** | 支持欺诈 / 真实 / 证据不足三种终局判决；Agent 可零追问，也可多轮追问；案例文档流式生成 |
| **检索式自学习** | 人工判决 → 案例文档 → 独立先例库 → 后续召回 → Beta(2,2) 反馈加权；不微调模型、不自动改规则 |
| **可观测** | SSE 事件流、断线续传、工具调用、RAG 命中、模型输出字段化渲染、对话记录常驻 |
| **成本控制** | 触发零 token、识图/第三方按图缓存、预算闸门、DeepSeek 谷值计费、按节点成本统计 |
| **双前端** | 管理观测台（深色）+ 模拟客服台（白 + 少量紫），演示台只通过对外 API 接入 |

---

## 架构

```text
外部客服平台 / 演示客服台
        │  /api/v1/analyze/*
        ▼
FastAPI Agent 服务（单 worker）
  ├─ 触发层：规则 + 关键词 + BGE 锚点余弦（零 LLM）
  ├─ LangGraph：取证 → AI 预检 → RAG/先例 → 视觉定位
  │              → 调查 ReAct → 一致性 → 裁决 → 报告
  ├─ 证据链 / 预算 / 缓存 / SSE 事件流
  ├─ SQLite（运行、事件、报告、复核、案例、反馈）
  └─ Chroma + BGE + BM25（知识库 / 先前案例，独立集合）
        │
        ├─ DeepSeek Flash（主推理）
        ├─ Qwen3.7-Flash（识图 / 篡改定位）
        ├─ Sightengine（AI 生成预检）
        └─ Tavily（联网事实）
```

### 一次分析的证据链

```text
触发判断（零 LLM）
  → 本地取证：EXIF / pHash 复用检测
  → AI 生成预检：Sightengine
  → 知识库召回：doctrine KB
  → 先前案例召回：人工判决沉淀
  → 视觉定位：Qwen 分区 + 篡改位置 + 诉求相关性
  → 调查 Agent：知识库 / 联网 / 识图 / 会话记录
  → 一致性核对 / 裁决 / 报告
  ↘ 人工复核 → 案例文档 → 先例索引 → 反馈加权
```

---

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.13、FastAPI、Pydantic v2、uvicorn（单 worker） |
| Agent | LangGraph、LangChain ReAct、条件回边、预算闸门 |
| 数据 | SQLite（WAL、外键、单写锁、迁移） |
| 检索 | Chroma、BAAI/bge-small-zh-v1.5（fastembed / ONNX / CPU）、jieba、BM25Plus、RRF |
| 主推理 | DeepSeek Flash（OpenAI 兼容接口） |
| 识图 | Qwen3.7-Flash（DashScope 兼容接口） |
| AI 生成检测 | Sightengine `genai`（不可见水印 / 模型指纹） |
| 联网 | Tavily |
| 前端 | Vue 3、Vite、TypeScript、Tailwind CSS、Axios、ECharts |
| 可观测 | SSE、事件先落库再发布、`Last-Event-ID` 断线续传、结构化模型输出 |

---

## 仓库结构

```text
match_project/
├─ backend/                 Agent API、LangGraph 流水线、RAG、SQLite
│  ├─ app/
│  │  ├─ agent/             图、节点、工具、提示词、预算、证据
│  │  ├─ api/               analyze / demo / admin 三组路由 + SSE
│  │  ├─ db/                SQLite、迁移、repositories
│  │  ├─ llm/               模型网关、假模型、价格表
│  │  ├─ observability/     事件、总线、回调、运行发射器
│  │  ├─ rag/               embedder / chunker / Chroma / BM25 / RRF
│  │  ├─ rules/             规则引擎、语义锚点、rules.yaml
│  │  └─ services/          复核、先例、Sightengine、演示服务
│  ├─ kb_seed/              示例知识库（首次启动复制到 data/kb）
│  ├─ scripts/              启动、模型下载、知识库导入、冒烟命令
│  └─ tests/                127 个后端测试
├─ frontend/                管理观测台（Vue 3，深色）
├─ demo_platform/
│  ├─ backend/              独立演示后端（FastAPI + SQLite）
│  └─ frontend/             模拟客服台（Vue 3，白 + 少量紫）
├─ docs/                    PPT 语料与技术选型材料
└─ 反AI生成内容欺骗行为agent.md   原始需求
```

> `backend/data/`、`demo_platform/backend/data/`、`.env`、`node_modules/`、`.venv/`、生成的 PPT/报告等不会提交到 Git。

---

## 快速开始

### 环境要求

- Python **3.13+**
- Node.js **20+**（当前验证 24.x）
- Git

### 1. 克隆仓库

```bash
git clone <your-repo-url>
cd match_project
```

### 2. 启动 Agent 后端（:8000）

```bash
cd backend
python -m venv .venv
```

Windows：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
copy .env.example .env
```

macOS / Linux：

```bash
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

编辑 `backend/.env`，填入模型网关、Sightengine、Tavily 等配置；如果只想先跑通链路，可以设置：

```env
LLM_MODE=fake
```

`fake` 模式不调用真实模型，适合本地联调与演示。

可选：预热本地向量模型 + 导入示例知识库：

```powershell
.venv\Scripts\python.exe scripts\download_models.py
.venv\Scripts\python.exe scripts\ingest_kb.py
```

启动：

```powershell
.venv\Scripts\python.exe scripts\run_server.py
```

- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/admin/health

首次启动会自动从 `kb_seed/` 复制示例知识库并初始化 Chroma；向量模型不可用时自动降级为 BM25-only，不影响服务启动。

### 3. 启动演示平台后端（:8001）

```bash
cd demo_platform/backend
python -m venv .venv
```

Windows：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\python.exe run.py
```

macOS / Linux：

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

演示后端默认连接 `http://127.0.0.1:8000`，其 `AGENT_API_KEY` 需要与 Agent 后端的 `EXTERNAL_API_KEY` 一致。

### 4. 启动前端

管理观测台：

```bash
cd frontend
npm install
npm run dev
```

模拟客服台：

```bash
cd demo_platform/frontend
npm install
npm run dev
```

### 5. 打开页面

| 页面 | 地址 |
|---|---|
| 管理观测台 | http://localhost:5173 |
| 模拟客服台 | http://localhost:5174 |
| Agent API 文档 | http://127.0.0.1:8000/docs |
| 演示平台后端文档 | http://127.0.0.1:8001/docs |

如果后端配置了非默认的 `ADMIN_API_KEY`，首次打开观测台时需要在右上角「访问密钥」中填入。

---

## 配置与安全

- **真实密钥只放在 `backend/.env`**，不要写进源码、前端、README、截图或提交记录。
- `.env`、`.env.*`、`backend/data/`、`demo_platform/backend/data/` 已在 `.gitignore` 中忽略；`.env.example` 只保留占位符，可以提交。
- 管理接口使用 `X-API-Key`（`ADMIN_API_KEY`），对外接口使用 `EXTERNAL_API_KEY`；未配置默认值时仅允许本机回环访问。
- 前端不接触模型/第三方密钥，只通过后端接口访问。
- 如果密钥曾经出现在聊天、截图、日志或公开仓库中，请立即到对应平台轮换。
- 演示数据为合成数据；不要将真实客户会话、图片或诊断材料提交到公开仓库。

---

## API 概览

| 分组 | 前缀 | 用途 |
|---|---|---|
| 对外分析 | `/api/v1/analyze` | `/check` 触发判断、`/runs` 启动/确认/取消/状态/报告、SSE 事件流 |
| 演示平台 | `/api/demo` | 会话、消息、图片上传、一键演示剧本、人工触发分析 |
| 管理面板 | `/api/admin` | 运行观测、事件流、工具调用、规则、知识库、先前案例、人工复核、统计、健康检查 |

完整字段与 curl 示例见 `backend/README.md` 和 http://127.0.0.1:8000/docs。

---

## 自学习边界

这里的「自学习」不是模型微调，也不是自动修改规则/阈值，而是：

1. 人工复核给出终局判决与理由；
2. Agent 按需追问，生成结构化案例文档；
3. 案例进入独立的先前案例索引；
4. 后续分析检索先例，作为证据链中的参考；
5. 被本案引用的先例按人工判决方向做 Beta(2,2) 反馈加权。

先例是**参照**，不是当前案件的结论；裁决必须比较相似点与差异，不能无条件照搬。

---

## 测试

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check app tests
```

前端构建：

```bash
cd frontend && npm run build
cd ../demo_platform/frontend && npm run build
```

当前状态：**127 个后端测试通过**，ruff 通过，两端前端 `vue-tsc` + Vite 构建通过。

---

## 文档

- `backend/README.md`：后端接口、流水线、RAG、复核与先例细节
- `demo_platform/README.md`：演示平台接入方式与演示流程
- `docs/ppt_prompt.md`：业务/技术评审 PPT 语料
- `docs/ppt_tech_selection_prompt.md`：主要技术选型 PPT 语料

---

## 使用边界

本系统是**辅助决策工具**，不替代人工责任：

- 模型与第三方检测都可能误判，结论必须结合证据链与人工复核；
- 不将系统输出作为唯一的退款、处罚或账号处置依据；
- 涉及医疗、隐私或敏感材料时，应遵守所在平台与地区的数据合规要求。

---

## License

当前仓库未附带开源许可证。如需公开分发或商用，请先补充 `LICENSE` 文件。
