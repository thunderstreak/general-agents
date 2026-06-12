# AI 应用任务计划

## 当前状态总览

| 模块 | 状态 | 优先级 | 当前实现 | 后续任务 |
|---|---|---|---|---|
| 配置管理 | 已完成 | P0 | `agent_app/config.py` 从 `.env` / 环境变量读取模型名、`base_url`、API key，并提供 `.env.example` | 后续可继续区分 dev/test/prod 配置 |
| 测试 | 未实现 | P0 | 当前主要靠手动命令验证 | 增加单元测试、工具 mock、意图分类测试、端到端测试 |
| 日志与可观测性 | 未实现 | P0 | 仅有工具调用 `print` | 增加 structured logging、trace id、耗时、token、工具输入输出记录 |
| 安全与权限 | 未实现 | P0 | 工具可直接调用外部接口 | 增加工具白名单、敏感操作确认、API key 保护、输入过滤 |
| Prompt 管理 | 已完成 | P1 | 意图分类 prompt 已拆分到 `agent_app/prompts/`，并提供分类样例文件 | 后续可继续增加版本管理和环境区分 |
| Intent Router 意图路由 | 已完成 | P1 | 已升级为 Tool Selector：基于工具元数据直接选择 `tool_name + args`，支持置信度、低置信度回退和样例检查脚本 | 后续可继续增强多意图和参数补全 |
| Tool 工具调用 | 已完成 | P1 | 已有 `get_location`、`get_weather`、`web_search`，并按领域拆分到 `agent_app/tools/`；工具运行时支持元数据、白名单、重试、统一错误格式和调用日志 | 后续可按工具复杂度继续增强人工确认和更细粒度权限 |
| State 状态管理 | 已实现但功能不全 | P1 | `AgentState` 当前只有 `messages` | 扩展结构化字段：`intent`、`retrieval_results`、`user_profile`、`tool_errors` |
| LLM 大模型 | 已实现但功能不全 | P1 | 使用 `ChatOpenAI` 接入第三方 `base_url`，支持聊天、工具选择、意图分类 | 补充模型 fallback、超时、token/cost 统计 |
| RAG 知识检索 | 未实现 | P2 | 暂无文档加载、向量化、向量库、检索链路 | 增加文档导入、embedding、vector store、retriever、引用来源输出 |
| Memory 记忆 | 已实现但功能不全 | P2 | `messages` 通过 LangGraph `add_messages` 保存当前进程内多轮上下文 | 增加长期记忆、用户偏好、历史摘要；接入数据库或文件存储 |
| Orchestrator 编排层 | 已实现但功能不全 | P2 | `agent_app/graph.py` 使用 LangGraph 编排 agent/tool 循环 | 增加 RAG 节点、memory 写入节点、失败分支、人工确认节点 |
| 数据存储 | 未实现 | P2 | 暂无数据库或文件存储 | 为 memory、RAG 文档、用户配置增加持久化存储 |
| 输出层 | 已实现但功能不全 | P3 | CLI 直接打印 `Agent: ...` | 增加结构化输出、Markdown 渲染、统一错误响应、API/前端输出层 |
| API / 服务化 | 未实现 | P3 | 目前通过 `index.py` 命令行运行 | 增加 FastAPI/HTTP API、会话管理、并发用户隔离 |

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

4. State 状态管理
   - 扩展 `AgentState`，保存 intent、工具错误、检索结果等结构化状态。

5. LLM 大模型
   - 增加模型 fallback。
   - 增加 timeout、token 和调用成本统计。

### P2：补齐知识与记忆能力

1. RAG 知识检索
   - 新增文档加载、切分、embedding、向量存储和检索工具。
   - 在 LangGraph 中增加 RAG 节点。

2. 长期 Memory
   - 增加用户画像和历史摘要存储。
   - 明确哪些信息允许写入长期记忆。

3. Orchestrator 编排层
   - 增加 RAG 节点、memory 写入节点、失败分支。
   - 为人工确认节点预留接口。

4. 数据存储
   - 为 RAG、长期记忆、会话记录增加持久化存储。

### P3：产品化与服务化

1. 输出层
   - 增加结构化输出和统一错误响应。
   - 支持 Markdown 渲染或前端/API 输出。

2. API / 服务化
   - 在 CLI 稳定后增加 HTTP API。
   - 支持多会话隔离和会话恢复。

## 当前结论

当前项目已经具备一个 LangGraph Agent 原型的核心骨架：LLM、工具调用、短期记忆、意图路由和基础编排已经可用。

距离完整 AI 应用还需要补齐 RAG、长期记忆、配置安全、测试、日志、权限控制、持久化和服务化能力。
