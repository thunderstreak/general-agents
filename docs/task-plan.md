# AI 应用任务计划

## 当前状态总览

| 模块 | 状态 | 优先级 | 当前实现 | 后续任务 |
|---|---|---|---|---|
| 配置管理 | 已完成 | P0 | `agent_app/config.py` 从 `.env` / 环境变量读取模型名、`base_url`、API key，并提供 `.env.example` | 后续可继续区分 dev/test/prod 配置 |
| 测试 | 未实现 | P0 | 当前主要靠手动命令验证 | 增加单元测试、工具 mock、意图分类测试、端到端测试 |
| 日志与可观测性 | 已实现但功能不全 | P0 | 工具调用仍有 `print`；编排层已记录 `trace_id`、节点运行耗时和成功/失败状态 | 增加 structured logging、token、工具输入输出持久化记录 |
| 安全与权限 | 未实现 | P0 | 工具可直接调用外部接口 | 增加工具白名单、敏感操作确认、API key 保护、输入过滤 |
| Prompt 管理 | 已完成 | P1 | 意图分类 prompt 已拆分到 `agent_app/prompts/`，并提供分类样例文件 | 后续可继续增加版本管理和环境区分 |
| Intent Router 意图路由 | 已完成 | P1 | 已升级为 Tool Selector：基于工具元数据直接选择 `tool_name + args`，支持置信度、低置信度回退和样例检查脚本 | 后续可继续增强多意图和参数补全 |
| Tool 工具调用 | 已完成 | P1 | 已有 `get_location`、`get_weather`、`web_search`，并按领域拆分到 `agent_app/tools/`；工具运行时支持元数据、白名单、重试、统一错误格式和调用日志 | 后续可按工具复杂度继续增强人工确认和更细粒度权限 |
| State 状态管理 | 已完成 | P1 | `AgentState` 已包含 `messages`、`tool_selection`、`tool_calls`、`tool_errors`、`retrieval_results`、`user_profile` | 后续随 RAG 和长期记忆继续扩展字段 |
| LLM 大模型 | 已完成 | P1 | 统一 `agent_app/llm.py` 管理聊天、工具选择、意图、视觉、Embedding 模型，支持 timeout、retry、fallback；CLI 支持 `@文件路径` 输入文本、文档、表格和图片 | 后续可继续补 token/cost 统计 |
| RAG 知识检索 | 未实现 | P2 | 已有 `EMBEDDING_MODEL_NAME`、`get_embedding_model()`、`retrieval_node`、`retrieval_results` 和输出层来源展示预留；尚未实现真实知识库导入、切分、向量化、Chroma 向量库和检索 | 第一版实现本地文件知识库、文本切分、embedding、Chroma vector store、retriever、引用来源输出和 CLI 知识库命令 |
| Memory 记忆 | 已完成 | P2 | `messages` 保存短期上下文；长期记忆会把用户明确要求记住的信息、偏好和历史摘要写入本地 JSON，并在模型调用前注入上下文 | 后续可增加记忆管理命令、隐私策略、语义检索和数据库存储 |
| Orchestrator 编排层 | 已完成 | P2 | `agent_app/graph.py` 使用 LangGraph 编排 retrieval/agent/tool/confirmation/memory/error/response 节点，支持循环保护、失败分支、人工确认预留、统一输出和节点 trace | 后续可接入真实 RAG、checkpoint 和多会话恢复 |
| 数据存储 | 未实现 | P2 | 当前仅有 `.agent_memory.json` 本地记忆文件；会话、RAG 文档/chunk 元数据、Chroma 向量索引、工具记录和 trace 尚未持久化 | 第一版使用 SQLite 存储 session、messages、memory、RAG 文档/chunk 元数据、tool runs、node runs 和用户配置；使用 Chroma 存储向量索引 |
| 输出层 | 已完成 | P3 | 已新增统一输出层，支持结构化响应、CLI 渲染、错误/确认状态、工具摘要、RAG 来源和 debug 输出 | 后续增加 API/前端输出适配和更丰富的 Markdown 渲染 |
| API / 服务化 | 未实现 | P3 | 目前通过 `index.py` 命令行运行；输出层已提供可复用的结构化 `final_response` | 增加 FastAPI HTTP API、内存 session store、会话创建/恢复、确认流程 API 化、健康检查和基础测试 |

## 任务优先级

### P0：立即处理

1. [x] 配置安全化
   - [x] 将 `OPENAI_API_KEY` 从代码迁移到环境变量。
   - [x] 增加 `.env.example` 说明必需配置。
   - [x] 增加 `.gitignore`，避免 `.env` 入库。

2. [ ] 测试基础建设
   - [ ] 增加 `pytest` 测试目录。
   - [ ] 为 `intent.py`、天气工具、定位工具、网页搜索工具补基础测试。

3. [ ] 日志与可观测性
   - [ ] 将工具调用 `print` 替换为统一日志。
   - [ ] 记录工具名称、参数、耗时、成功/失败状态。
   - [x] 编排层记录 `trace_id` 和节点运行耗时。

4. [ ] 安全与权限
   - [x] 避免敏感配置入库。
   - [ ] 为未来危险工具预留人工确认机制。

### P1：稳定核心 Agent 能力

1. [x] Prompt 管理
   - [x] 将意图分类 prompt 拆到独立文件。
   - [x] 为 prompt 增加分类样例和预期输出。
   - [ ] 增加 prompt 版本管理和环境区分。

2. [x] Intent Router 意图路由
   - [x] 增加分类测试集。
   - [x] 增加分类失败或低置信度时的 fallback 策略。
   - [x] 升级为基于工具元数据的 Tool Selector。
   - [ ] 增强多意图处理和参数补全。

3. [x] Tool 工具调用
   - [x] 增加工具元数据和统一错误格式。
   - [x] 增加工具级重试和日志。
   - [x] 增加工具白名单检查。

4. [x] State 状态管理
   - [x] 扩展 `AgentState`，保存工具选择、工具调用、工具错误、检索结果、用户画像等结构化状态。

5. [x] LLM 大模型
   - [x] 增加按用途配置多模型。
   - [x] 增加模型 fallback。
   - [x] 增加 timeout、retry 配置。
   - [x] 增加图片、文档、文件输入解析能力。
   - [ ] 增加 token 和调用成本统计。

### P2：补齐知识与记忆能力

1. RAG 知识检索
   - [ ] 复用文件解析模块导入本地文档，支持 `.txt`、`.md`、`.json`、`.csv`、`.pdf`、`.docx`、`.xlsx`。
   - [ ] 增加文本 chunk 切分能力，支持 chunk size 和 overlap 配置。
   - [ ] 调用 `get_embedding_model()` 将 chunk 向量化。
   - [ ] 使用 Chroma 作为向量数据库，保存 chunk embedding 和 metadata。
   - [ ] 增加 Chroma 配置，例如 `CHROMA_PERSIST_DIR=.chroma`、`CHROMA_COLLECTION_NAME=agent_knowledge`。
   - [ ] 增加 retriever，根据用户问题生成 query embedding 并返回 top_k 相似 chunk。
   - [ ] 将 `retrieval_node` 的 placeholder 替换为真实检索结果。
   - [ ] 将检索结果注入模型上下文，回答时要求引用来源。
   - [ ] 输出层展示文档名、路径、chunk id、score 等来源信息。
   - [ ] 增加 CLI 知识库维护命令，例如 `rag add @文件路径`、`rag list`、`rag clear`。
   - [ ] 增加 RAG 测试：导入、切分、检索、无结果回退、来源输出。

2. 长期 Memory
   - [x] 增加用户画像和历史摘要存储。
   - [x] 明确只自动写入用户明确要求记住的信息、名字和偏好。
   - [x] 增加本地 JSON 持久化存储。
   - [ ] 增加记忆查看、删除和清空命令。
   - [ ] 增加语义检索和数据库存储。

3. Orchestrator 编排层
   - [x] 增加 RAG 预留节点。
   - [x] 增加 memory 写入节点。
   - [x] 增加失败分支。
   - [x] 为人工确认节点预留接口。
   - [x] 增加循环保护和统一输出节点。
   - [ ] 接入真实 RAG 检索链路。
   - [ ] 增加 checkpoint 和多会话恢复。

4. 数据存储
   - [ ] 选择第一版存储方案：优先使用 SQLite，避免一开始引入复杂数据库。
   - [ ] 增加数据库配置，例如 `DATABASE_URL=sqlite:///agent_app.db`。
   - [ ] 新增数据库初始化模块，负责建表和连接管理。
   - [ ] 增加 `sessions` 表，保存 `session_id`、用户标识、创建时间、更新时间和状态摘要。
   - [ ] 增加 `messages` 表，保存每轮 Human/AI/Tool message，支持会话恢复。
   - [ ] 增加 `memory_items` 表，替代或兼容当前 `.agent_memory.json`，支持按用户/会话隔离长期记忆。
   - [ ] 增加 `documents` 表，保存 RAG 文档 id、文件名、路径、hash、导入时间和 metadata。
   - [ ] 增加 `document_chunks` 表，保存 chunk id、document id、内容、顺序、token 估算和 metadata。
   - [ ] RAG 向量索引使用 Chroma；SQLite 只保存文档和 chunk 业务元数据，以及 Chroma collection/chunk id 的映射关系。
   - [ ] 增加 `tool_runs` 表，保存工具名、参数、结果、成功/失败、耗时和错误信息。
   - [ ] 增加 `node_runs` 表，保存 `trace_id`、节点名、耗时、成功/失败和错误信息。
   - [ ] 增加 `user_configs` 表，保存用户偏好、模型配置、输出配置和权限配置。
   - [ ] 增加数据隔离策略，确保不同用户、session、知识库之间不会串数据。
   - [ ] 增加数据清理能力：删除会话、清空记忆、删除文档、重建索引。
   - [ ] 增加轻量 schema migration 机制，便于后续表结构升级。
   - [ ] 增加数据存储测试：建表、CRUD、会话恢复、memory 迁移、RAG 文档/chunk 元数据写入和删除。
   - [ ] 后续增强：Redis session 缓存、PostgreSQL 生产库、Chroma server 模式、数据加密、数据导入/导出、过期会话 TTL。

### P3：产品化与服务化

1. 输出层
   - [x] 增加结构化输出和统一错误响应。
   - [x] 支持 CLI 渲染、错误/确认状态、工具摘要、RAG 来源和 debug 输出。
   - [ ] 支持更丰富的 Markdown 渲染或前端/API 输出。

2. API / 服务化
   - [ ] 增加 FastAPI 服务入口，例如 `agent_app/api.py`。
   - [ ] 新增 `fastapi`、`uvicorn` 依赖和启动说明。
   - [ ] 定义 `ChatRequest`、`ChatResponse` 等请求/响应模型，复用输出层 `final_response`。
   - [ ] 增加 `POST /chat`，支持 `message` 和可选 `session_id`，无 session 时自动创建。
   - [ ] 增加内存 session store，按 `session_id` 保存独立 Agent state，避免多用户上下文串线。
   - [ ] 增加会话恢复能力，有 `session_id` 时继续原会话。
   - [ ] 增加确认流程接口，例如 `POST /sessions/{session_id}/confirm` 或在 chat 请求中传确认结果。
   - [ ] 增加 `GET /health` 健康检查。
   - [ ] 增加 `GET /sessions/{session_id}` 和 `DELETE /sessions/{session_id}`，便于调试和释放内存。
   - [ ] 增加 HTTP 统一错误响应，不向客户端暴露 traceback。
   - [ ] 增加 CORS 配置，为后续前端接入预留。
   - [ ] 为内存 session store 增加最小锁保护，避免并发请求同时修改同一会话。
   - [ ] 第一版暂不做文件上传，后续再支持 multipart 文件上传并复用文件解析模块。
   - [ ] 增加 API 测试：health、chat、session 续聊、确认流程、错误响应。
   - [ ] 后续增强：SQLite/Redis 会话持久化、用户鉴权、请求限流、SSE/WebSocket 流式输出、Docker 部署。

## 当前结论

当前项目已经具备一个 LangGraph Agent 原型的核心骨架：LLM、工具调用、短期记忆、意图路由和基础编排已经可用。

距离完整 AI 应用还需要补齐 RAG、长期记忆、配置安全、测试、日志、权限控制、持久化和服务化能力。
