# AI 应用任务计划

## 当前状态总览

| 模块 | 状态 | 优先级 | 当前实现 | 后续任务 |
|---|---|---|---|---|
| 配置管理 | 已完成 | P0 | `agent_app/config.py` 从 `.env` / 环境变量读取模型名、`base_url`、API key，并提供 `.env.example` | 后续可继续区分 dev/test/prod 配置 |
| 测试 | 已实现但不完整 | P0 | 已有 `unittest` 覆盖 memory、graph、nodes、output、CLI stream、CLI session、session store、CLI input、state、message utils 等基础行为；节点测试已按领域拆分 | 增加模型 mock、工具 mock、工具选择样例自动化、端到端测试 |
| 日志与可观测性 | 已实现但功能不全 | P0 | 编排层已记录 `trace_id`、节点运行耗时和成功/失败状态；CLI 流式输出可展示节点/工具/RAG 阶段进度；`OUTPUT_DEBUG=true` 时在最终响应后输出 debug 信息 | 增加 structured logging、token/cost 统计、工具输入输出持久化记录、loop/stop reason |
| 安全与权限 | 已完成基础防护 | P0 | 敏感配置通过 `.env` 管理；工具运行时已有白名单检查；URL Fetch 禁止 localhost、内网 IP 和 metadata 地址；确认节点已预留并支持需要确认的工具 | 增加更细粒度权限策略、危险工具确认、API key 脱敏日志和输入过滤 |
| 感知理解 | 已完成基础节点 | P1 | 已新增 `perception_node`，统一生成 `input_context`，记录原始文本、标准化文本、附件摘要、文件解析错误、图片需求、RAG 触发信号和候选工具名；CLI 仍负责 `@文件路径` 解析 | 后续增加模型能力校验、输入事件结构、API 文件输入复用和更细多模态判断 |
| Prompt 管理 | 已完成 | P1 | 工具选择 prompt 已拆分到 `agent_app/prompts/`，并提供样例文件；历史 Intent Router prompt 已清理 | 后续可继续增加版本管理和环境区分 |
| 规划决策 | 已完成基础结构 | P1 | 已新增 `planning_node`，使用本地工具意图 gate 生成 `chat/tool_agent` plan；工具模式会记录候选工具名，只把候选工具绑定给模型；当工具模式模型未产生真实 `tool_calls` 时，会对 `web_search`/`fetch_url` 生成确定性 fallback tool call；Tool Selector 降级为兼容路径 | 继续增强多步任务拆解、参数补全、低置信度追问和 plan 推进 |
| Tool 工具调用 | 已完成 | P1 | 已有 `get_location`、`get_weather`、`get_weather_forecast`、`web_search`、`fetch_url`，并按领域拆分到 `agent_app/tools/`；`web_search` 已改为 Tavily Search API；工具 metadata 与工具模块就近声明，注册中心只汇总；工具运行时支持元数据、白名单、重试、统一错误格式、结构化 ToolRunRecord 和调用日志 | 后续可按工具复杂度继续增强人工确认和更细粒度权限 |
| State 状态管理 | 已完成 | P1 | `agent_app/state.py` 统一维护 `AgentState`、初始 state、单轮 reset 和旧会话默认值补齐；state 已包含 `messages`、`input_context`、`tool_selection`、`plan`、`reflection`、`tool_calls`、`conversation_summary` 和压缩计数等字段 | 后续随 RAG 和长期记忆继续扩展字段 |
| LLM 大模型 | 已完成 | P1 | 统一 `agent_app/llm.py` 管理聊天、工具选择、视觉模型和 OpenAI embedding 辅助函数；graph/tool selector 已改为延迟初始化模型；LLM 调用前后会检查取消标记；CLI 支持 `@文件路径` 输入文本、文档、表格和图片 | 后续可继续补 token/cost 统计和更细模型能力检测 |
| RAG 知识检索 | 已完成本地 MVP | P2 | 已接入本地文件知识库、`documents.json` 文档 metadata、`chunks.jsonl` chunk metadata、RecursiveCharacterTextSplitter 切分、HuggingFace/OpenAI embedding provider 切换、embedding 实例缓存、Chroma 持久化索引、`retrieval_node` 真实检索、RAG 阶段进度、基础来源 metadata、来源输出、`/rag` CLI 命令、`/rag sync`、`/rag rebuild`、查询规范化和本地关键词 rerank | 下一阶段补长期记忆语义检索、更完整 hybrid search、LLM query rewrite、专业 reranker 和生产级 metadata 存储 |
| Memory 记忆 | 已完成但检索弱 | P2 | `messages` 保存短期上下文；长期记忆会把用户明确要求记住的信息、偏好和历史摘要写入本地 JSON，并在模型调用前注入上下文；会话上下文压缩已支持 `/compact`、自动压缩、摘要注入和归档 | 增加记忆管理命令、隐私策略、长期记忆语义检索和更细粒度存储 |
| 反思评估 | 已完成基础闭环 | P2 | `reflection_node` 已优先基于结构化工具结果决策，支持结果不足判断、参数缺失追问、临时错误重试、不可重试失败、停止原因、`fetch_url -> web_search` 换工具和 planning 联动；关键词判断仅作旧记录兼容 | 后续增强 LLM Judge、更多工具 fallback 和复杂结果质量判断 |
| 循环迭代控制 | 已完成基础结构 | P2 | 已有 `ORCHESTRATOR_MAX_STEPS` 防止无限循环；reflection 可路由到 agent/tools/planning/response/error，并记录 retry/stop/loop reason 和 attempted tools | 增加更细的工具级 retry policy 和多步 plan 推进 |
| Orchestrator 编排层 | 已完成基础编排 | P2 | `agent_app/graph.py` 负责 LangGraph 图构建和路由，`agent_app/nodes/` 按领域拆分节点实现；支持 perception/retrieval/planning/agent/tool/confirmation/reflection/memory/error/response 编排、循环保护、失败分支、人工确认预留、统一输出和节点 trace | 多步 plan 推进和更细可观测性 |
| 数据存储 | 已实现基础会话保存 | P2 | 已有 `.agent_memory.json` 长期记忆和 `.agent_sessions/` 文件夹式会话历史；每个会话保存 state、可读消息日志和压缩归档；RAG 文档/chunk metadata 与 Chroma 向量索引已本地持久化；工具运行记录和 trace 尚未独立持久化 | 补齐工具运行记录、节点 trace、用户配置和数据清理能力 |
| 输出层 | 已完成 | P3 | 已新增统一输出层，支持结构化响应、CLI 渲染、错误/确认状态、工具摘要、RAG 来源和 debug 输出；CLI 流式渲染已拆分到 `agent_app/cli_stream.py`，debug 只在最终 `final_response` 后输出 | 后续增加 API/前端输出适配和更丰富的 Markdown 渲染 |
| CLI 交互体验 | 已完成基础体验 | P3 | 使用 `prompt_toolkit` 改善中文输入、方向键和历史；任务运行通过 worker thread 执行，Esc/Ctrl+C 可让 CLI 立即停止等待并回到输入提示；普通输入阶段 Ctrl+C 不打印 traceback | 后续隔离后台 worker 输出，必要时升级为 worker process + IPC 输出队列 |
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
| 感知理解 | 已有 `perception_node` 输出标准化 `input_context`；`file_inputs/parser.py` 可解析文本、JSON、CSV、PDF、DOCX、XLSX、图片；图片会标记 `requires_vision` | 第一阶段只做本地结构化理解，尚未校验当前模型是否真的支持视觉，也未统一 CLI/API 输入事件 | 增加模型能力校验、输入事件结构和 API 文件输入复用 |
| 记忆检索 | `with_memory_context()` 注入长期记忆；`retrieval_node` 已接入 Chroma 文档 retriever；RAG 支持 sync/rebuild 和本地关键词 rerank | 长期记忆仍是直接注入，不做语义检索；RAG 暂未支持专业 reranker 和 LLM query rewrite | 下一阶段补长期记忆语义检索和更高级检索 |
| 规划决策 | `planning_node` 优先读取 `input_context.normalized_text` 和 `candidate_tool_names`，使用本地工具意图 gate 生成 `chat/tool_agent` 结构化 plan | 当前仍是单步轻量 planning，不支持多步任务拆解、参数补全和计划推进 | 增强多步 planning，支持低置信度追问和 plan 状态推进 |
| 工具调用 | `agent_node` 对 `tool_agent` plan 调用绑定工具模型，由模型原生 tool calling 生成 `tool_calls`；若模型未调用工具，会基于候选工具对 `web_search`/`fetch_url` 生成 fallback tool call；router 进入 tools | 当前只支持单轮工具调用和轻量工具模式判断 | 扩展为多工具/多意图计划，支持工具结果聚合 |
| 执行 | `tool_node()` 调用 `run_tool()`，支持白名单、重试、错误格式和耗时记录 | 工具运行记录未持久化；失败策略较粗 | 持久化 tool runs，增加按错误类型的 retry policy |
| 反思 | 工具后进入 `reflection_node`，优先读取 ToolRunRecord 的 `result_status/error_type/is_retryable/fallback_tool_names/missing_info` 决定总结、重试、追问、换工具或失败 | 暂未支持 LLM Judge 和复杂质量判断 | 增强更多工具 fallback、重新规划策略和复杂结果质量评估 |
| 输出 | `response_node()` 生成统一 `final_response`，CLI 支持普通/流式渲染；debug 信息只在最终响应后输出 | Markdown/API/前端适配仍基础 | 增加更丰富 Markdown 渲染和 API 输出适配 |

## 任务优先级

### P0：立即处理

1. [x] 配置安全化
   - [x] 将 `OPENAI_API_KEY` 从代码迁移到环境变量。
   - [x] 增加 `.env.example` 说明必需配置。
   - [x] 增加 `.gitignore`，避免 `.env` 入库。

2. [ ] 测试基础建设
   - [x] 增加 `unittest` 测试目录和基础测试。
   - [x] 为网页搜索工具补 mock 测试。
   - [ ] 为天气工具、定位工具补 mock 测试。
   - [x] 为 URL Fetch 工具补 mock 测试。
   - [x] 为 message utils 和 state 初始化补单元测试。
   - [x] 将 `test_orchestrator.py` 拆分为 graph 和 nodes 领域测试文件。
   - [ ] 为工具选择和端到端链路增加模型 mock 测试。

3. [ ] 日志与可观测性
   - [x] 将工具调用进度从直接 `print` 收敛为 LangGraph custom progress 事件。
   - [x] 记录工具名称、耗时、成功/失败状态和结构化结果摘要。
   - [x] 编排层记录 `trace_id` 和节点运行耗时。
   - [x] CLI debug 信息只在最终 `final_response` 生成后输出，避免穿插在长回答中间。
   - [ ] 增加 structured logging、token/cost 统计和独立 trace 持久化。

4. [x] 安全与权限
   - [x] 避免敏感配置入库。
   - [x] 工具运行时支持工具白名单检查。
   - [x] URL Fetch 默认阻断 localhost、内网 IP 和 metadata 地址，降低 SSRF 风险。
   - [x] 为未来危险工具预留人工确认机制。
   - [ ] 后续增加更细粒度权限策略和 API key 脱敏日志。

### P1：稳定核心 Agent 能力

1. [x] Prompt 管理
   - [x] 将意图分类 prompt 拆到独立文件。
   - [x] 为 prompt 增加分类样例和预期输出。
   - [ ] 增加 prompt 版本管理和环境区分。

2. [x] Intent Router 意图路由
   - [x] 历史 Intent Router 已由 `planning_node` 和 tool-agent 主链路替代。
   - [x] 清理 `agent_app/intent.py`、旧 intent prompt、旧 intent 样例和检查脚本。
   - [x] 升级为基于工具元数据和候选工具绑定的 Tool Selector/tool-agent。
   - [ ] 增强多意图处理和参数补全。

3. [ ] Planning 规划决策
   - [x] 增加 `planning_node` 或结构化 plan 输出。
   - [x] 在 `AgentState` 中增加 `plan`，统一保存 `plan_steps`、`current_step`、`decision_reason`。
   - [x] 将 `tool_selector` 结果纳入明确的 plan step。
   - [x] 增加本地快速意图短路，明显普通对话跳过工具选择模型。
   - [x] 改为本地工具意图 gate，明确工具意图进入 `tool_agent`，由绑定工具模型决策具体工具。
   - [x] 基于工具 metadata 先筛选候选工具，再绑定给 tool-agent 模型，降低工具增多后的上下文占用。
   - [x] 当 tool-agent 未产生真实工具调用时，针对 `web_search` 和 `fetch_url` 生成 fallback tool call，避免“提示调用工具但未调用”。
   - [ ] 支持多步任务拆解、参数补全和低置信度追问。

4. [x] Tool 工具调用
   - [x] 增加工具元数据和统一错误格式。
   - [x] 将工具 metadata 就近声明到工具模块内，注册中心只负责汇总。
   - [x] 增加工具级重试和日志。
   - [x] 增加工具白名单检查。
   - [x] 增加结构化 ToolRunRecord，包含 `result_status`、`error_type`、`missing_info`、`is_retryable`、`fallback_tool_names`。
   - [x] 新增 `fetch_url` URL 抓取工具，并对 SSRF 和不支持正文内容做结构化结果分类。
   - [x] 将 `web_search` 重写为 Tavily Search，并保留项目统一 `web_search(query: str) -> str` 外壳。
   - [ ] 支持多工具调用计划和工具结果聚合。

5. [x] State 状态管理
   - [x] 扩展 `AgentState`，保存工具选择、工具调用、工具错误、检索结果、用户画像等结构化状态。
   - [x] 扩展 `AgentState`，保存 planning 结构。
   - [x] 扩展 `AgentState`，保存 reflection 结构。
   - [x] 扩展 `AgentState`，保存单轮 `input_context` 感知结果。
   - [x] 扩展 `AgentState`，保存 `conversation_summary`、`compact_count` 和 `last_compacted_at`。
   - [x] 将 `AgentState`、初始 state、单轮 reset 和旧会话默认值补齐集中到 `agent_app/state.py`。
   - [ ] 扩展 `AgentState`，保存 loop reason 和 stop reason。

6. [x] LLM 大模型
   - [x] 增加按用途配置多模型。
   - [x] 增加模型 fallback。
   - [x] 增加 timeout、retry 配置。
   - [x] 增加图片、文档、文件输入解析能力。
   - [x] 将 graph 和 tool selector 的模型实例改为延迟初始化，避免导入时创建模型。
   - [x] LLM 调用前后检查取消标记，配合 CLI worker 取消减少继续执行。
   - [ ] 增加 token 和调用成本统计。

7. [ ] 代码结构优化
   - [x] 提取公共 `agent_app/utils/messages.py`，统一 LangChain message 文本提取。
   - [x] 提取 `agent_app/cli_stream.py`，拆分 CLI 流式输出渲染。
   - [x] 拆分 `graph.py` 节点实现与图构建：`graph.py` 保留图入口和路由，`nodes/` 承载节点实现。
   - [x] 将 `nodes.py` 继续拆为 `nodes/` 包，按 retrieval、planning、agent、tools、reflection、memory、response 等领域组织。
   - [x] 拆分过大的 `test_orchestrator.py`，按 graph/nodes 领域组织测试。
   - [x] 清理历史 `agent_app/intent.py` 和样例检查脚本，避免维护两套意图路由。
   - [x] 提取 `agent_app/context_compaction.py`，封装会话上下文压缩逻辑。
   - [x] 提取 `agent_app/cli_cancel.py`，封装 Esc/Ctrl+C 取消与 worker thread 执行器。
   - [ ] 后续继续拆分 CLI 命令处理逻辑。

8. [x] CLI 交互体验
   - [x] 使用 `prompt_toolkit` 替代原生 `input()`，改善 macOS 中文输入、删除和方向键体验。
   - [x] CLI 默认流式输出，普通聊天不展示无意义“检索中/规划中/思考中”。
   - [x] 首响应等待期使用临时 `处理中...` 状态，不提前打印 `Agent:`。
   - [x] 任务运行中支持 Esc/Ctrl+C 取消；当前实现使用 worker thread，让 CLI 立即回到输入提示。
   - [x] 输入阶段 Ctrl+C 只取消当前输入，不打印 traceback。
   - [ ] 后续隔离后台 worker stdout，必要时升级为 worker process + IPC 输出队列。

### P2：补齐知识与记忆能力

1. RAG 知识检索
   - [x] 第一阶段：本地 RAG MVP
     - [x] 新增依赖：`langchain-chroma`、`chromadb`、`langchain-huggingface`、`sentence-transformers`、`langchain-text-splitters`。
     - [x] 新增配置：`RAG_ENABLED=true`、`RAG_STORE_DIR=.agent_knowledge`、`CHROMA_PERSIST_DIR=.agent_knowledge/chroma`、`CHROMA_COLLECTION_NAME=agent_knowledge`。
     - [x] 新增 embedding 配置：`RAG_EMBEDDING_PROVIDER=huggingface|openai`、`RAG_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5`，支持切换 OpenAI embedding。
     - [x] 新增 chunk 配置：`RAG_CHUNK_SIZE=800`、`RAG_CHUNK_OVERLAP=120`、`RAG_TOP_K=4`。
     - [x] 复用文件解析模块导入本地文档，支持 `.txt`、`.md`、`.json`、`.csv`、`.pdf`、`.docx`、`.xlsx`。
     - [x] 使用 `RecursiveCharacterTextSplitter` 切分文本，生成稳定 `document_id`、`chunk_id`、`chunk_index` 和 `content_hash`。
     - [x] 使用 HuggingFaceEmbeddings 将 chunk 向量化，写入 Chroma，并保存 chunk metadata。
     - [x] 支持项目内本地 HuggingFace 模型目录，例如 `./models/bge-small-zh-v1.5`。
     - [x] 缓存 embedding 实例，避免同一 CLI 进程重复加载本地模型。
     - [x] RAG 检索阶段显示“首次加载本地 embedding 模型 / 生成查询向量 / 查询知识库 / 整理知识库结果”等进度。
     - [x] 使用 `.agent_knowledge/documents.json` 保存文档级 metadata，包括路径、hash、标题、导入时间、chunk 数量和 active 状态。
     - [x] 使用 `.agent_knowledge/chunks.jsonl` 保存 chunk 业务 metadata，便于人工查看和后续迁移到 SQLite。
     - [x] 将 `retrieval_node` 的 placeholder 替换为真实 Chroma 检索，写入 `retrieval_results`。
     - [x] 复用 `agent_node.with_context()` 注入检索上下文，回答时要求引用来源。
     - [x] 复用输出层来源展示，显示文档名、路径、chunk id、score 等基础来源信息。
     - [x] 增加 CLI 知识库维护命令：`/rag add <文件路径>`、`/rag list`、`/rag delete <document_id>`、`/rag clear`。
     - [x] 增加 RAG 测试：文档导入、hash 去重、切分、Chroma 写入、检索、无结果回退、来源输出和 CLI 命令。
   - [x] 第二阶段：知识更新与同步
     - [x] 增加 `/rag sync`，根据文件路径和 content hash 检测变更。
     - [x] 增加 `/rag rebuild`，清空并重建 Chroma 索引。
     - [x] 文档更新时删除旧 chunk vectors，再重新切分、embedding 和写入。
     - [x] 增强来源 metadata：页码、sheet 名、chunk id、score 和文档版本。
   - [ ] 第三阶段：生产化存储
     - [ ] 评估 SQLite 保存 RAG 文档和 chunk 业务 metadata；Chroma 只保存向量和最小 metadata。
     - [ ] 增加 schema migration、多用户/多知识库隔离、数据清理和索引一致性检查。
   - [ ] 第四阶段：高级检索
     - [ ] 增加长期记忆语义检索，把相关 memory 和 RAG 结果一起注入上下文。
     - [x] 增加查询规范化、本地 keyword boost 和轻量 rerank。
     - [ ] 增加更完整 hybrid search、专业 reranker、LLM query rewrite 和多文档引用格式优化。

2. 长期 Memory
   - [x] 增加用户画像和历史摘要存储。
   - [x] 明确只自动写入用户明确要求记住的信息、名字和偏好。
   - [x] 增加本地 JSON 持久化存储。
   - [x] 增加会话上下文压缩：`/compact`、`/compact show`、`/compact clear`。
   - [x] 支持按消息数阈值自动压缩上下文，并将压缩摘要注入后续模型上下文。
   - [x] 被压缩移除的短期消息会追加到 `messages.archive.jsonl`。
   - [ ] 增加记忆查看、删除和清空命令。
   - [ ] 增加语义检索和数据库存储。

3. Orchestrator 编排层
   - [x] 增加 `perception_node`，作为图入口统一整理输入上下文。
   - [x] 增加 RAG 预留节点。
   - [x] 增加 memory 写入节点。
   - [x] 增加失败分支。
   - [x] 为人工确认节点预留接口。
   - [x] 增加循环保护和统一输出节点。
   - [x] 接入真实 RAG 检索链路。
   - [x] 接入 `planning_node`，让普通回答和工具 agent 模式来自结构化计划。
   - [ ] 增强 `planning_node`，让追问、多步任务和参数补全也来自结构化计划。
   - [x] 接入轻量 `reflection_node`，检查工具结果是否失败。
   - [x] 增强 `reflection_node`，检查工具结果是否充分、是否需要重试或补充提问。
   - [x] 支持反思后回到 planning/agent/tool，或进入 response。
   - [x] 增加基础 stop reason 和 retry policy。
   - [x] 增强基础换工具策略、loop reason 和 attempted tools。
   - [x] tool-agent 模式支持候选工具 fallback，避免模型未产出 tool call 时直接回答。
   - [ ] 增强更多工具 fallback、工具级 retry policy 和多步 plan 推进。
   - [x] 增加文件夹式会话历史保存和手动恢复。

4. 数据存储
   - [x] 增加 `.agent_sessions/` 文件夹式会话历史保存。
   - [x] 保存 `metadata.json`、`state.json`、`messages.jsonl`。
   - [x] 上下文压缩归档消息保存到 `messages.archive.jsonl`。
   - [x] 支持 CLI 手动 `/sessions`、`/resume`、`/new`、`/delete`、`/current`。
   - [ ] 评估是否仍需要 SQLite 保存生产级 session/messages/tool runs。
   - [ ] 增加 `memory_items` 表，替代或兼容当前 `.agent_memory.json`，支持按用户/会话隔离长期记忆。
   - [x] RAG 第一版使用 `.agent_knowledge/documents.json` 和 `.agent_knowledge/chunks.jsonl` 保存文档/chunk metadata，Chroma 保存向量和检索 metadata。
   - [ ] 生产化阶段再增加 `documents` 表，保存 RAG 文档 id、文件名、路径、hash、导入时间和 metadata。
   - [ ] 生产化阶段再增加 `document_chunks` 表，保存 chunk id、document id、内容、顺序、token 估算和 metadata。
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
   - [x] 检查工具结果是否为空、是否不足以继续回答。
   - [x] 检查工具失败是否可重试、是否需要向用户追问。
   - [x] 将反思结果写入 `state["reflection"]`，包含 `status`、`reason`、`next_action`、`missing_info`、`retry_tool_name`、`retry_count`、`stop_reason`。
   - [x] 增加反思节点测试：成功通过、失败、重试、追问、结果不足、达到循环上限。
   - [x] 增强基础换工具策略和 planning 联动。
   - [x] 将 Reflection 主判断改为结构化工具结果驱动，关键词判断降级为 legacy fallback。
   - [ ] 增强更多工具 fallback 和 LLM Judge。

### P3：产品化与服务化

1. 输出层
   - [x] 增加结构化输出和统一错误响应。
   - [x] 支持 CLI 渲染、错误/确认状态、工具摘要、RAG 来源和 debug 输出。
   - [x] CLI debug 信息只在最终 `final_response` 生成后输出，不穿插在超长模型回答中间。
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

当前项目已经具备一个可用的 LangGraph Agent 原型：LLM、工具调用、短期记忆、长期记忆、文件夹式会话历史、上下文压缩、本地 RAG 知识库、流式 CLI、Esc 取消、基础 Perception、结构化 Planning 和 Reflection 闭环已经可用。

当前链路里的感知理解已从分散在 CLI、retrieval 和 planning 中的隐式判断，整理为 `perception -> retrieval -> planning -> agent` 的显式链路；工具调用和执行已经比较明确，规划决策已从直接 Tool Selector 升级为本地工具意图 gate + 结构化 plan + tool-agent 模式，并通过候选工具绑定和 fallback tool call 降低“提示调用工具但未调用”的概率；反思评估已从关键词规则升级为结构化工具结果驱动，并支持结果质检、追问、重试、换工具和多路由。

RAG 已完成本地文件知识库 MVP、知识更新同步、embedding 缓存、基础来源 metadata、查询规范化和本地关键词 rerank；CLI 已支持 prompt_toolkit 输入、流式输出、worker thread 取消和最终 debug 输出。距离完整 agentic workflow 还需要补齐多步规划、长期记忆语义检索、更强 hybrid search、专业 reranker、LLM query rewrite、工具/trace 持久化、token/cost 统计和更强可观测性。
