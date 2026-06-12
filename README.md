# LangGraph Agent

这是一个基于 LangGraph 和 LangChain 的命令行 Agent 项目。项目通过 CLI 接收用户输入，使用 OpenAI-compatible 模型完成对话、规划决策、工具调用、长期记忆写入和统一响应输出。

## 功能概览

- 多轮命令行对话。
- 基于 LangGraph 的节点编排。
- 支持 OpenAI-compatible API，包括官方 OpenAI 或第三方兼容服务。
- 支持轻量 Planning（规划决策），普通对话默认直接回答；明确工具意图会进入可调用工具的 agent 模式。
- 支持天气、IP 定位、网页搜索、URL 内容抓取等工具调用。
- 支持本地长期记忆，默认写入 `.agent_memory.json`。
- 支持通过 `@文件路径` 读取文本、图片、PDF、DOCX、XLSX、CSV、JSON 等文件输入。
- 保留 RAG（Retrieval-Augmented Generation，检索增强生成）节点结构，当前为占位实现。
- CLI 默认支持流式输出，并可显示检索、工具调用、记忆更新等节点进度。
- 支持调试输出 trace、节点耗时、工具摘要和错误详情。

## 环境要求

- Python 3.10 或更高版本。
- 可访问的 OpenAI-compatible API 服务。
- 可用的 `OPENAI_API_KEY`。

## 快速开始

### 1. 拉取代码

```bash
git clone <your-repo-url>
cd langgraph
```

### 2. 创建虚拟环境

macOS / Linux:

```bash
python3 -m venv venv
source venv/bin/activate
```

Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置环境变量

复制示例配置：

```bash
cp .env.example .env
```

然后编辑 `.env`，至少填写：

```dotenv
BASE_URL=https://your-openai-compatible-api/v1
OPENAI_API_KEY=your-api-key
MODEL_NAME=your-model-name
CHAT_MODEL_NAME=your-model-name
TOOL_SELECTOR_MODEL_NAME=your-model-name
VISION_MODEL_NAME=your-vision-model-name
```

如果只想用同一个模型，可以保留 `MODEL_NAME`，并让其他模型配置沿用示例值。

### 5. 运行项目

```bash
python index.py
```

启动后会看到：

```text
LangGraph Agent 启动 (输入 'quit' 退出)
```

输入问题即可对话，输入 `quit` 退出。

CLI 默认开启流式输出，会先显示节点进度，再逐步打印最终回答。如果需要恢复为整轮完成后一次性输出，可以在 `.env` 中设置：

```dotenv
CLI_STREAM=false
```

如果只想保留回答流式输出、不显示节点进度，可以设置：

```dotenv
CLI_STREAM_PROGRESS=false
```

## 使用示例

普通对话：

```text
你: 介绍一下 LangGraph 的核心概念
```

天气查询：

```text
你: 查询北京今天的天气
```

网页搜索：

```text
你: 搜索今天 OpenAI 的最新消息
```

URL 内容抓取：

```text
你: 总结 https://example.com 这篇文章
```

文件输入：

```text
你: 总结这个文件 @docs/task-plan.md
你: 分析这个表格 @"./data/report.xlsx"
```

长期记忆：

```text
你: 请记住：我喜欢简洁的中文回答
```

## 配置说明

配置文件通过 `python-dotenv` 从 `.env` 加载，定义在 `agent_app/config.py`。

| 变量名 | 是否必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `BASE_URL` | 否 | 空 | OpenAI-compatible API 地址，例如 `https://api.openai.com/v1` 或第三方兼容服务地址。 |
| `OPENAI_API_KEY` | 是 | 无 | API key。真实值只写入本地 `.env`，不要提交到 Git。 |
| `MODEL_NAME` | 否 | 空 | 默认模型名，兼容旧配置。 |
| `CHAT_MODEL_NAME` | 否 | `MODEL_NAME` | 主聊天模型，用于普通对话和工具结果总结。 |
| `TOOL_SELECTOR_MODEL_NAME` | 否 | `MODEL_NAME` | 工具选择模型，用于判断是否调用工具以及生成工具参数。 |
| `VISION_MODEL_NAME` | 否 | `MODEL_NAME` | 多模态视觉模型，用于图片输入。模型和服务需要支持图片。 |
| `EMBEDDING_MODEL_NAME` | 否 | `text-embedding-3-small` | Embedding 模型，为后续 RAG 检索预留。 |
| `FALLBACK_MODEL_NAME` | 否 | 空 | 备用模型。主聊天模型失败时使用，留空表示不启用。 |
| `MODEL_TIMEOUT_SECONDS` | 否 | `60` | 模型请求超时时间，单位秒。 |
| `MODEL_MAX_RETRIES` | 否 | `2` | 模型请求失败后的最大重试次数。 |
| `MEMORY_FILE_PATH` | 否 | `.agent_memory.json` | 长期记忆本地 JSON 文件路径。 |
| `MEMORY_MAX_ITEMS` | 否 | `50` | 最多保留的长期记忆条数。 |
| `ORCHESTRATOR_MAX_STEPS` | 否 | `8` | 单轮编排最多进入 agent/tool 节点的次数，用于避免工具循环。 |
| `OUTPUT_DEBUG` | 否 | `false` | 是否在 CLI 输出 trace、节点耗时、工具摘要和错误详情。 |
| `CLI_STREAM` | 否 | `true` | 是否开启 CLI 流式输出。关闭后会等待整轮执行完成再输出。 |
| `CLI_STREAM_PROGRESS` | 否 | `true` | 流式输出时是否显示检索、工具调用、记忆更新等进度。 |
| `CLI_INPUT_HISTORY_FILE` | 否 | `.agent_input_history` | CLI 输入历史文件，用于支持上下键查看历史输入。 |
| `SESSION_STORE_DIR` | 否 | `.agent_sessions` | 文件夹式历史会话存储目录。 |
| `SESSION_AUTO_SAVE` | 否 | `true` | 是否在每轮对话后自动保存当前会话。 |

## 项目架构

```text
langgraph/
├── index.py                         # CLI 启动入口
├── requirements.txt                 # Python 依赖
├── .env.example                     # 环境变量示例
├── agent_app/
│   ├── cli.py                       # 命令行交互循环
│   ├── cli_stream.py                # CLI 流式输出渲染
│   ├── config.py                    # 环境变量和运行配置
│   ├── graph.py                     # LangGraph 图构建和路由
│   ├── nodes.py                     # LangGraph 节点实现
│   ├── state.py                     # AgentState 和 state 初始化
│   ├── llm.py                       # 模型实例、fallback 和 embedding 管理
│   ├── orchestrator.py              # 编排辅助结构、trace 和错误状态
│   ├── output.py                    # 统一响应结构和 CLI 渲染
│   ├── memory.py                    # 长期记忆读写和上下文注入
│   ├── tool_selector.py             # 基于模型的工具选择器
│   ├── prompt_loader.py             # prompt 文件加载
│   ├── prompts/                     # prompt 和样例数据
│   ├── tools/                       # 工具注册、运行时和具体工具
│   ├── utils/                       # 通用 helper
│   └── file_inputs/                 # @文件路径 输入解析
├── scripts/                         # prompt 样例检查脚本
├── tests/                           # 单元测试
└── docs/                            # 项目文档
```

## 核心流程

项目入口是 `index.py`，它调用 `agent_app.cli.run_cli()` 启动命令行。

单轮请求的主要流程如下：

```text
用户输入
  ↓
CLI 解析文本和 @文件路径
  ↓
LangGraph: retrieval 节点
  ↓
LangGraph: planning 节点
  ↓
LangGraph: agent 节点
  ↓
根据路由进入 tools / confirm / memory / error
  ↓
工具执行后进入 reflection 核对结果
  ↓
核对通过后回到 agent 总结结果
  ↓
memory 节点写入长期记忆
  ↓
response 节点生成统一响应
  ↓
CLI 渲染输出
```

### LangGraph 节点说明

- `retrieval`：RAG 检索预留节点。命中“知识库、文档、检索”等关键词时写入占位检索结果。
- `planning`：使用本地工具意图 gate 生成结构化 `plan`；普通对话生成 `chat` plan，明确工具/实时/RAG/文件/记忆意图生成 `tool_agent` plan。
- `agent`：读取 `plan` 决定普通聊天，或使用绑定工具的模型生成原生 `tool_calls`。
- `confirm`：处理需要人工确认的工具调用。当前注册工具默认不需要确认。
- `tools`：通过统一工具运行时执行工具，记录耗时、重试次数和错误。
- `reflection`：轻量核对工具结果是否成功，成功后回到 `agent` 总结，失败时进入错误响应。
- `memory`：在最终回复后更新长期记忆。
- `error`：构造统一错误消息。
- `response`：输出统一结构，供 CLI 渲染。

## 工具系统

工具函数和 `ToolMetadata` 就近放在各自工具模块内，`agent_app/tools/__init__.py` 只负责汇总注册。

当前内置工具：

- `get_location`：通过公网 IP 查询大致位置，数据源为 `ip-api.com`。
- `get_weather`：查询指定城市实时天气；未提供城市时会尝试通过 IP 定位城市，数据源为 `wttr.in`。
- `web_search`：通过 DuckDuckGo 和 Bing 搜索网页，返回标题、链接和摘要。
- `fetch_url`：抓取指定 HTTP/HTTPS URL 的文本内容，禁止访问 localhost 和内网地址。

工具统一由 `agent_app/tools/runtime.py` 执行，支持：

- 工具白名单校验。
- 最大重试次数。
- 运行耗时记录。
- 统一错误格式。
- 人工确认开关。
- 基于 `ToolMetadata.trigger_keywords` 先筛选候选工具，再绑定给 tool-agent 模型，减少工具数量增加后的上下文占用。

## 文件输入

CLI 支持在用户输入中使用 `@文件路径` 引用本地文件。

支持的类型：

- 文本：`.txt`、`.md`
- 结构化文本：`.json`、`.csv`
- 文档：`.pdf`、`.docx`、`.xlsx`
- 图片：`.png`、`.jpg`、`.jpeg`、`.webp`

示例：

```text
你: 总结 @docs/task-plan.md
你: 识别这张图片 @"./images/demo.png"
```

图片会以多模态输入发送给模型，因此 `VISION_MODEL_NAME` 对应的模型和 API 服务必须支持图片输入。

## 长期记忆

长期记忆逻辑在 `agent_app/memory.py`。

默认记忆文件：

```text
.agent_memory.json
```

触发方式包括：

- `请记住：...`
- `记住：...`
- `以后记得：...`
- `我叫...`
- `我喜欢...`

`.agent_memory.json` 已在 `.gitignore` 中忽略，不应提交到仓库。

## 历史会话

CLI 启动时默认创建新会话，不会自动恢复上一次对话。历史会话会自动保存到：

```text
.agent_sessions/
```

每个会话一个目录，包含：

- `metadata.json`：会话标题、更新时间、消息数量等摘要。
- `state.json`：完整 Agent state，用于恢复会话。
- `messages.jsonl`：可读消息日志，便于直接查看历史。

可用命令：

```text
/sessions
/resume <session_id>
/new
/delete <session_id>
/current
```

说明：

- `.agent_sessions/` 保存完整会话历史，可手动恢复。
- `.agent_memory.json` 保存长期记忆摘要和用户偏好。
- 删除 `.agent_sessions/` 可以清空所有历史会话。

## 测试

运行单元测试：

```bash
python -m unittest discover tests
```

运行工具选择器样例检查：

```bash
python scripts/check_tool_selector_examples.py
```

注意：样例检查会真实调用模型，因此需要 `.env` 中的模型配置可用。

## 开发说明

- `agent_app/graph.py` 负责 LangGraph 图构建和路由；`agent_app/nodes.py` 负责节点实现。模型实例采用延迟初始化，避免导入模块时立即创建 LLM。
- `agent_app/state.py` 统一维护 `AgentState`、初始 state、单轮 state reset 和旧会话默认值补齐。
- `agent_app/utils/` 存放通用 helper；其中 `utils/messages.py` 提供 LangChain message 文本提取，避免各模块重复解析消息结构。
- `agent_app/cli.py` 保留 CLI 主循环、输入读取和会话命令；`agent_app/cli_stream.py` 负责流式 chunk 解析、进度输出和 debug 尾部渲染。
- 新增工具时，需要在 `agent_app/tools/` 下实现工具函数，并在同一模块声明 `TOOL_METADATA`；然后在 `agent_app/tools/__init__.py` 导入工具函数和 metadata 进行汇总注册。
- 新增 prompt 时，放入 `agent_app/prompts/`，通过 `prompt_loader.load_prompt()` 读取。
- 需要调整单轮最大编排次数时，修改 `.env` 中的 `ORCHESTRATOR_MAX_STEPS`。
- 需要查看调试信息时，设置 `OUTPUT_DEBUG=true`。

## 常见问题

### 启动时报缺少 `OPENAI_API_KEY`

请确认已经复制并填写 `.env`：

```bash
cp .env.example .env
```

并确保 `.env` 中包含有效的：

```dotenv
OPENAI_API_KEY=your-api-key
```

### 工具调用失败

天气、定位、网页搜索和 URL 抓取依赖外部网络服务。如果网络不可用、服务限流、页面结构变化或目标站点限制访问，工具可能返回失败信息。

### macOS 中文输入无法删除或移动光标

CLI 使用 `prompt_toolkit` 读取输入，用来改善中文输入、删除、左右方向键和上下历史输入体验。输入历史默认写入：

```text
.agent_input_history
```

如果仍然出现中文编辑异常，请先确认终端 locale 是 UTF-8：

```bash
locale
```

### 图片无法识别

请确认：

- 输入路径正确。
- 文件扩展名为 `.png`、`.jpg`、`.jpeg` 或 `.webp`。
- `VISION_MODEL_NAME` 对应的模型支持图片输入。
- `BASE_URL` 对应的服务支持 OpenAI-compatible 多模态消息格式。
