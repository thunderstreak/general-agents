# AGENTS.md

本文件为 AI 编码代理提供项目约定和开发指南。

## 代码风格

- 所有注释、docstring、用户提示均使用**简体中文**
- 技术术语保留英文（如 `ToolMetadata`、`LangGraph`、`StateGraph`）
- 模块顶部用 `"""模块说明。"""` 单行 docstring
- 函数/类用 `"""描述。"""` 中文 docstring，句号结尾
- 变量命名使用 snake_case，类名使用 PascalCase
- 私有函数以 `_` 前缀（如 `_format_tool_error`、`_latest_human_message`）
- 类型注解使用 Python 3.10+ 语法（`dict[str, Any]`、`float | None`）

## 添加新工具

1. 在 `agent_app/tools/` 下新建模块，定义一个 `@tool` 装饰的函数
2. 在 `agent_app/tools/__init__.py` 中：
   - 导入新工具函数
   - 添加到 `tools` 列表
   - 添加对应的 `ToolMetadata` 到 `tool_metadata` 列表
3. 工具函数必须返回字符串结果（LLM 会读取）
4. 如需确认执行，设置 `requires_confirmation=True`

## 添加新图节点

1. 在 `agent_app/graph.py` 中定义节点函数，签名为 `(state: AgentState) -> dict`
2. 每个节点必须返回 `node_runs` 列表（调用 `_node_run()` 生成）
3. 步骤计数受限的节点需调用 `_next_step_state()` 检查上限
4. 在 `build_graph()` 中注册节点并添加边/条件边
5. 路由函数返回 `Literal` 类型，值对应 `build_graph()` 中的边映射键

## LangGraph State 约定

- `messages` 使用 `Annotated[list, add_messages]`，LangGraph 自动追加
- 累积型字段（`tool_calls`、`node_runs` 等）使用 `Annotated[list, operator.add]`
- 节点返回的 dict 只包含要更新的字段，不要返回完整 state
- 错误通过 `last_error` 字段传递，由 `error_state()` 构造统一格式

## 测试

- 使用 `unittest` 框架（非 pytest），测试类继承 `unittest.TestCase`
- 测试文件放在 `tests/` 目录，命名为 `test_<模块>.py`
- 用辅助函数构造 state 字典作为测试输入（参考 `test_output.py` 的 `_state()`）
- 运行：`python -m pytest tests/` 或 `python -m unittest discover tests/`

## 配置管理

- 所有配置从 `.env` 读取，由 `agent_app/config.py` 统一导出为模块级常量
- 添加新配置项：在 `config.py` 中用 `os.getenv()` 读取并设默认值
- 必需配置用 `_get_required_env()` 读取，缺失时抛出 `RuntimeError`
- 同步更新 `.env.example` 并加中文注释

## LLM 调用

- 通过 `agent_app/llm.py` 的 `get_*_model()` 函数获取模型实例（已缓存）
- 需要 fallback 时用 `invoke_with_fallback(messages)`
- 新增模型用途：在 `config.py` 加环境变量 → `llm.py` 加 `get_*_model()` 函数

## Prompt 管理

- Prompt 模板放在 `agent_app/prompts/` 目录，使用 Markdown 格式
- Few-shot 示例用同目录下的 `.examples.json` 文件
- 通过 `agent_app/prompt_loader.py` 加载

## 文件输入

- 用户输入支持 `@filepath` 语法引用文件
- 支持格式：txt、md、json、csv、pdf、docx、xlsx、图片
- 解析逻辑在 `agent_app/file_inputs/parser.py`

## 注意事项

- `.env` 和 `.agent_memory.json` 已加入 `.gitignore`，不要提交
- 编排步骤有上限（默认 8 步），通过 `ORCHESTRATOR_MAX_STEPS` 配置
- `retrieval` 节点当前为占位符，仅关键字触发，未接入实际向量数据库
