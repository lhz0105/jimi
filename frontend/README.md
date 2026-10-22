# 迹觅·Evidence 观测台（管理面板前端）

Vue 3 + Vite + TypeScript 实现的管理观测台，对接 `backend/` 的 `/api/admin` 等接口，
用于观测 agent 的**输入 / 输出 / 思考过程 / tool calling / RAG 命中**，并管理知识库与规则。

> 演示客服平台前端本次不做（按需求）；后端接口已全部就绪（见 `backend/README.md`）。

## 快速开始

```bash
cd frontend
npm install            # 依赖已配置国内镜像（registry.npmmirror.com）

# 开发态（Vite 代理 /api、/files、/docs 到 127.0.0.1:8000，无需处理跨域）
npm run dev            # http://localhost:5173

# 生产构建（同源部署：由后端/网关反代 /api）
npm run build

# 生产构建（独立部署：前端 4173、后端 8000，浏览器直连跨域）
VITE_API_BASE=http://127.0.0.1:8000 npm run build
npm run preview        # http://localhost:4173
```

后端需先启动：`cd ../backend && .venv\Scripts\python.exe scripts\run_server.py`。

## 页面

| 路由 | 功能 |
|---|---|
| `/` 总览 | 服务健康（DB / RAG / 规则 / LLM / SSE 连接数）、近 7 天指标卡、运行量与成本趋势、场景分布、最近运行 |
| `/runs` 运行记录 | 状态 / 场景 / 关键词筛选（同步到 URL，可分享）、自动刷新、分页 |
| `/runs/:id` 运行详情 | **实时事件流（SSE）**、报告（Markdown / JSON）、工具调用清单、原始事件；结论卡、按节点成本、规则决策、输入摘要、证据链、取消运行、导出报告/事件流 |
| `/knowledge` 知识库 | 文档列表与增删、增量/全量重建、**检索调试**（dense / bm25 / RRF 三路分数） |
| `/rules` 规则 | YAML 编辑器、保存（服务端 schema 校验，失败保留旧版）、从磁盘重载、字段速查 |
| `/system` 系统 | 健康详情、模型网关（密钥脱敏）、预算闸门、数据目录、Swagger 入口 |

## 关键实现

- **SSE 客户端**（`src/composables/useEventStream.ts`）：基于 `fetch` + `ReadableStream` 手写 SSE 解析，
  原因：原生 `EventSource` 无法带 `X-API-Key` 头。特性：
  - 断线自动重连（1.5s），携带 `?from_seq=<lastSeq>` 续传——服务端从 DB 回放缺失事件，**不丢事件**；
  - 收到 `run_end` 或确认运行已终态后自动停止；支持暂停 / 继续 / 重放（从头重连）；
  - 渲染上限 500 条（完整事件在「原始事件」页签，避免长列表卡顿）。
- **API 客户端**（`src/api/client.ts`）：axios 实例；`X-API-Key` 从 localStorage 注入（顶栏钥匙按钮设置）；
  统一把后端的 `{error:{code,message,detail}}` 信封归一化为 `ApiError`。
- **设计令牌**（`src/style.css`）：深色 Swiss 运维台配色（底 `#0F172A` / 卡 `#1B2336` / 边框 `#475569` /
  状态色 绿-黄-红 + 蓝-紫-青），密度 8/10 紧凑节奏；等宽数字（tabular-nums）避免跳动；
  尊重 `prefers-reduced-motion`；统一可见焦点环。
- **无障碍**：语义化角色（导航 / 表格 / 对话框 / tablist）、图标一律 SVG（无 emoji）、
  图标按钮带 `aria-label`、颜色不作为唯一信息载体（状态徽章均含文字）、Toast 使用 `aria-live="polite"`、
  对话框支持 Esc 关闭与打开后聚焦、表单均有显式 label。
- **图表**：ECharts 按需引入（Bar/Line + Grid/Tooltip/Legend），并作为异步组件加载，
  不阻塞首屏（首屏 ~40KB gzip，图表库另在 180KB gzip 的分块中按需拉取）。

## 跨域说明

两种部署方式都已验证：

1. **开发态 / 同源部署**：Vite 代理（`vite.config.ts` 中 `/api`、`/files`、`/docs`）→ 无跨域问题。
2. **独立部署**：后端已开启 `CORSMiddleware`，白名单来自 `backend/.env` 的 `CORS_ORIGINS`
   （默认含 `http://localhost:5173` 与 `http://localhost:4173`）。前端用 `VITE_API_BASE` 指向后端地址即可；
   非白名单来源不会返回 `Access-Control-Allow-Origin`。
   若前端部署在其它端口/域名，把地址追加到 `CORS_ORIGINS`（逗号分隔）后重启后端。

## 访问密钥

后端 `ADMIN_API_KEY` 为默认占位值（`change-me-admin`）时，本机访问免密钥；
配置了真实密钥后，点顶栏钥匙按钮填入即可（仅存 localStorage，随 `X-API-Key` 头发送，SSE 同样携带）。
