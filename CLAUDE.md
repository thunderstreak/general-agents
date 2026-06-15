# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 常用命令

```bash
pip install -r requirements.txt    # 安装依赖
python index.py                    # 运行 Agent（CLI 交互）
python -m unittest discover tests  # 运行全部测试
python -m pytest tests/test_memory.py   # 运行单个测试
python scripts/check_intent_examples.py      # 验证意图分类（需 API）
python scripts/check_tool_selector_examples.py  # 验证工具选择器（需 API）
```

## 架构

基于 LangChain + LangGraph 的中文对话 Agent，支持工具调用、长期记忆、文件输入解析。通过 `.env` 配置 OpenAI 兼容 API 端点。

### 核心流程（LangGraph 状态图）

定义在 `agent_app/graph.py`，节点流转：

```
retrieval → agent → [confirm | tools | error | memory]
                      tools → [agent | error]
                      memory → [response | error]
                      confirm/error/memory → response → END
```

- `agent` — 主 LLM 节点，先经 `tool_selector.py` 决定走工具/对话/自动
- `tools` — 通过 `tools/runtime.py` 统一执行，含白名单、重试、日志
- `confirm` — 需确认工具的人工门控
- `memory` — JSON 文件长期记忆（`memory.py`），提取显式记忆 + 对话摘要
- `retrieval` — RAG 占位符（仅关键字触发，未完整实现）

### 工具系统

注册在 `agent_app/tools/__init__.py`，每个工具有 `ToolMetadata`。当前工具：`get_location`（IP 定位）、`get_weather`（天气）、`web_search`（DuckDuckGo + Bing 抓取）。

### 文件输入

`agent_app/file_inputs/parser.py` 支持 `@filepath` 语法，解析 txt/md/json/csv/pdf/docx/xlsx/图片（base64 多模态）。图片需 `VISION_MODEL_NAME` 对应模型支持多模态。

### LLM 管理

`agent_app/llm.py` 用 `@lru_cache` 按用途管理多个 `ChatOpenAI` 实例（chat、tool_selector、vision 等），均通过环境变量配置。支持 fallback 模型（`invoke_with_fallback()`）。

### 会话管理

CLI 支持多会话，存储在 `.agent_sessions/` 目录。每个会话含 `metadata.json`、`state.json`、`messages.jsonl`。CLI 命令：`/sessions`、`/resume <id>`、`/new`、`/delete <id>`、`/current`。

### 流式输出

CLI 默认开启流式输出（`CLI_STREAM=true`），支持节点进度显示（`CLI_STREAM_PROGRESS=true`）。

## 配置

所有配置在 `.env` 中（参考 `.env.example`），由 `agent_app/config.py` 加载。关键项：各用途模型名、API Base URL、超时、记忆文件路径、编排最大步数、流式输出开关、会话存储目录。
