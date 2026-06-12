# AI 应用任务计划

## 当前状态总览

| 模块 | 状态 | 优先级 | 当前实现 | 后续任务 |
|---|---|---|---|---|
| 配置管理 | 已完成 | P0 | `agent_app/config.py` 从 `.env` / 环境变量读取模型名、`base_url`、API key，并提供 `.env.example` | 后续可继续区分 dev/test/prod 配置 |
| 测试 | 已实现但不完整 | P0 | 已有 `unittest` 覆盖 memory、orchestrator、output、CLI stream、CLI session、session store、CLI input 等基础行为 | 增加模型 mock、工具 mock、意图/工具选择样例自动化、端到端测试 |
| 日志与可观测性 | 已实现但功能不全 | P0 | 编排层已记录 `trace_id`、节点运行耗时和成功/失败状态；CLI 流式输出可展示节点进度 | 增加 structured logging、token/cost 统计、工具输入输出持久化记录、loop/stop reason |
| 安全与权限 | 未实现 | P0 | 工具可直接调用外部接口 | 增加工具白名单、敏感操作确认、API key 保护、输入过滤 |
| 感知理解 | 已实现但分散 | P1 | CLI 支持文本输入和 `@文件路径`，文件解析模块支持文本、文档、表格、图片输入 | 增加统一 perception 节点，规范输入解析结果、附件元数据和多模态能力判断 |
| Prompt 管理 | 已完成 | P1 | 意图分类 prompt 已拆分到 `agent_app/prompts/`，并提供分类样例文件 | 后续可继续增加版本管理和环境区分 |
| 规划决策 | 已完成基础结构 | P1 | 已新增 `planning_node`，使用本地工具意图 gate 生成 `chat/tool_agent` plan；工具模式会记录候选工具名，只把候选工具绑定给模型；Tool Selector 降级为兼容路径 | 继续增强多步任务拆解、参数补全、低置信度追问和 plan 推进 |
| Tool 工具调用 | 已完成 | P1 | 已有 `get_location`、`get_weather`、`web_search`、`fetch_url`，并按领域拆分到 `agent_app/tools/`；工具 metadata 与工具模块就近声明，注册中心只汇总；工具运行时支持元数据、白名单、重试、统一错误格式和调用日志 | 后续可按工具复杂度继续增强人工确认和更细粒度权限 |
| State 状态管理 | 已完成 | P1 | `AgentState` 已包含 `messages`、`tool_selection`、`plan`、`reflection`、`tool_calls`、`tool_errors`、`retrieval_results`、`user_profile` | 后续随 RAG 和长期记忆继续扩展字段 |
| LLM 大模型 | 已完成 | P1 | 统一 `agent_app/llm.py` 管理聊天、工具选择、意图、视觉、Embedding 模型，支持 timeout、retry、fallback；CLI 支持 `@文件路径` 输入文本、文档、表格和图片 | 后续可继续补 token/cost 统计 |
| RAG 知识检索 | 未实现 | P2 | 已有 `EMBEDDING_MODEL_NAME`、`get_embedding_model()`、`retrieval_node`、`retrieval_results` 和输出层来源展示预留；尚未实现真实知识库导入、切分、向量化、Chroma 向量库和检索 | 第一版实现本地文件知识库、文本切分、embedding、Chroma vector store、retriever、引用来源输出和 CLI 知识库命令 |
| Memory 记忆 | 已完成但检索弱 | P2 | `messages` 保存短期上下文；长期记忆会把用户明确要求记住的信息、偏好和历史摘要写入本地 JSON，并在模型调用前注入上下文 | 增加记忆管理命令、隐私策略、长期记忆语义检索和更细粒度存储 |
| 反思评估 | 已完成基础结构 | P2 | 已新增轻量 `reflection_node`，工具执行后核对成功/失败，成功回到 `agent_node` 总结，失败进入错误响应 | 增强结构化反思：判断结果是否充分、是否需要重试/换工具/补充提问 |
| 循环迭代控制 | 弱实现 | P2 | 已有 `ORCHESTRATOR_MAX_STEPS` 防止无限循环；工具后可回到 agent | 增加 loop reason、stop reason、retry policy、反思后回到 planning/tool/response 的路由 |
| Orchestrator 编排层 | 已完成基础编排 | P2 | `agent_app/graph.py` 使用 LangGraph 编排 retrieval/planning/agent/tool/confirmation/reflection/memory/error/response 节点，支持循环保护、失败分支、人工确认预留、统一输出和节点 trace | 接入真实 RAG、增强 reflection、plan 推进和更细路由 |
| 数据存储 | 已实现基础会话保存 | P2 | 已有 `.agent_memory.json` 长期记忆和 `.agent_sessions/` 文件夹式会话历史；RAG 文档/chunk 元数据、Chroma 向量索引、工具记录和 trace 尚未持久化 | 补齐 RAG 元数据、工具运行记录、节点 trace、用户配置和数据清理能力 |
| 输出层 | 已完成 | P3 | 已新增统一输出层，支持结构化响应、CLI 渲染、错误/确认状态、工具摘要、RAG 来源和 debug 输出 | 后续增加 API/前端输出适配和更丰富的 Markdown 渲染 |
| API / 服务化 | 未实现 | P3 | 目前通过 `index.py` 命令行运行；输出层已提供可复用的结构化 `final_response` | 增加 FastAPI HTTP API、内存 session store、会话创建/恢复、确认流程 API 化、健康检查和基础测试 |

## Agent 工作流程链路现状

目标链路：

```text
用户输入 → 感知理解 → 记忆检索 → 规划决策 → 工具调用 → 执行 → 反思 → 输出
    ↑                                                              │
    └──────────────────── 循环迭代 ──────────────────────────────────┘
```

| 阶段 | 当前实现 | 缺口 | 后续任务 |
|---|---|---|---|
| 用户输入 | CLI 支持 `prompt_toolkit` 输入、流式输出、文件引用和会话命令 | 尚无统一输入事件结构 | 将文本、文件、会话命令统一封装为输入事件 |
| 感知理解 | `file_inputs/parser.py` 可解析文本、JSON、CSV、PDF、DOCX、XLSX、图片 | 没有独立 perception 节点；附件能力和模型能力未统一校验 | 增加 `perception_node`，输出标准化 `input_context` 和附件元数据 |
| 记忆检索 | `with_memory_context()` 注入长期记忆；`retrieval_node` 仅保留 RAG placeholder | 缺少真实 RAG 检索和长期记忆语义检索 | 接入 Chroma retriever，增加 memory semantic search |
| 规划决策 | `planning_node` 使用本地工具意图 gate 生成 `chat/tool_agent` 结构化 plan | 当前仍是单步轻量 planning，不支持多步任务拆解、参数补全和计划推进 | 增强多步 planning，支持低置信度追问和 plan 状态推进 |
| 工具调用 | `agent_node` 对 `tool_agent` plan 调用绑定工具模型，由模型原生 tool calling 生成 `tool_calls`，router 进入 tools | 当前只支持单轮工具调用和轻量工具模式判断 | 扩展为多工具/多意图计划，支持工具结果聚合 |
| 执行 | `tool_node()` 调用 `run_tool()`，支持白名单、重试、错误格式和耗时记录 | 工具运行记录未持久化；失败策略较粗 | 持久化 tool runs，增加按错误类型的 retry policy |
| 反思 | 工具后进入 `reflection_node`，按成功/失败核对工具结果，再回到 `agent_node` 总结或进入错误响应 | 当前是规则化轻量反思，不判断结果充分性 | 增强 `reflection_node`，决定重试、换工具、追问或输出 |
| 输出 | `response_node()` 生成统一 `final_response`，CLI 支持普通/流式渲染 | Markdown/API/前端适配仍基础 | 增加更丰富 Markdown 渲染和 API 输出适配 |

## 任务优先级

### P0：立即处理

1. [x] 配置安全化
   - [x] 将 `OPENAI_API_KEY` 从代码迁移到环境变量。
   - [x] 增加 `.env.example` 说明必需配置。
   - [x] 增加 `.gitignore`，避免 `.env` 入库。

2. [ ] 测试基础建设
   - [x] 增加 `unittest` 测试目录和基础测试。
   - [ ] 为天气工具、定位工具、网页搜索工具补 mock 测试。
   - [x] 为 URL Fetch 工具补 mock 测试。
   - [ ] 为工具选择、规划、反思和端到端链路增加模型 mock 测试。

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

3. [ ] Planning 规划决策
   - [x] 增加 `planning_node` 或结构化 plan 输出。
   - [x] 在 `AgentState` 中增加 `plan`，统一保存 `plan_steps`、`current_step`、`decision_reason`。
   - [x] 将 `tool_selector` 结果纳入明确的 plan step。
   - [x] 增加本地快速意图短路，明显普通对话跳过工具选择模型。
   - [x] 改为本地工具意图 gate，明确工具意图进入 `tool_agent`，由绑定工具模型决策具体工具。
   - [x] 基于工具 metadata 先筛选候选工具，再绑定给 tool-agent 模型，降低工具增多后的上下文占用。
   - [ ] 支持多步任务拆解、参数补全和低置信度追问。

4. [x] Tool 工具调用
   - [x] 增加工具元数据和统一错误格式。
   - [x] 将工具 metadata 就近声明到工具模块内，注册中心只负责汇总。
   - [x] 增加工具级重试和日志。
   - [x] 增加工具白名单检查。
   - [ ] 支持多工具调用计划和工具结果聚合。

5. [x] State 状态管理
   - [x] 扩展 `AgentState`，保存工具选择、工具调用、工具错误、检索结果、用户画像等结构化状态。
   - [x] 扩展 `AgentState`，保存 planning 结构。
   - [x] 扩展 `AgentState`，保存 reflection 结构。
   - [ ] 扩展 `AgentState`，保存 loop reason 和 stop reason。

6. [x] LLM 大模型
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
   - [ ] 增加长期记忆语义检索，把相关记忆和 RAG 结果一起注入上下文。

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
   - [x] 接入 `planning_node`，让普通回答和工具 agent 模式来自结构化计划。
   - [ ] 增强 `planning_node`，让追问、多步任务和参数补全也来自结构化计划。
   - [x] 接入轻量 `reflection_node`，检查工具结果是否失败。
   - [ ] 增强 `reflection_node`，检查工具结果是否充分、是否需要重试/换工具/补充提问。
   - [ ] 支持反思后回到 planning/agent/tool，或进入 response。
   - [ ] 增加更细的 loop reason、stop reason 和 retry policy。
   - [x] 增加文件夹式会话历史保存和手动恢复。

4. 数据存储
   - [x] 增加 `.agent_sessions/` 文件夹式会话历史保存。
   - [x] 保存 `metadata.json`、`state.json`、`messages.jsonl`。
   - [x] 支持 CLI 手动 `/sessions`、`/resume`、`/new`、`/delete`、`/current`。
   - [ ] 评估是否仍需要 SQLite 保存生产级 session/messages/tool runs。
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

5. Reflection 反思评估
   - [x] 增加 `reflection_node`。
   - [ ] 检查工具结果是否回答了用户问题。
   - [ ] 检查工具失败是否可重试、是否需要换工具、是否需要向用户追问。
   - [x] 将反思结果写入 `state["reflection"]`，包含 `status`、`reason`、`next_action`。
   - [ ] 增加反思节点测试：成功通过、失败重试、换工具、追问、达到循环上限。

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

当前项目已经具备一个 LangGraph Agent 原型的核心骨架：LLM、工具调用、短期记忆、长期记忆、文件夹式会话历史、流式 CLI、结构化 Planning 第一阶段和基础编排已经可用。

当前链路里的工具调用和执行已经比较明确，规划决策已从直接 Tool Selector 升级为本地工具意图 gate + 结构化 plan + tool agent 模式；反思评估已有轻量节点，但仍缺少结果充分性判断和重试/换工具策略。RAG 仍是 placeholder，循环迭代只靠最大步数保护。

距离完整 agentic workflow 还需要补齐多步规划、结构化反思、真实知识检索、记忆语义检索、循环决策、工具/trace 持久化和更强可观测性。
