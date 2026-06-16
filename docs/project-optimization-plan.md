一、需要拆分的文件（按优先级排序）
  
  1. cli.py (426行) → 拆分为3个文件

  cli.py          →  cli_app.py         # 主入口和会话管理
                     cli_commands.py     # 命令处理 (/sessions, /resume 等)
                     cli_utils.py        # 工具函数

  理由：当前文件混杂了会话管理、命令解析、用户输入处理等多种职责

  2. nodes/agent.py (255行) → 拆分为2个文件

  nodes/agent.py  →  nodes/agent_core.py    # Agent 节点核心逻辑
                     nodes/agent_helpers.py  # 辅助函数

  理由：该文件导入了 11 个内部模块，是耦合度最高的文件

  3. tools/runtime.py (258行) → 拆分为2个文件

  tools/runtime.py → tools/executor.py     # 工具执行器
                     tools/registry.py     # 工具注册和发现

  4. rag/store.py (520行) → 拆分为2-3个文件

  rag/store.py    →  rag/store.py         # ChromaStore 核心
                     rag/query.py         # 查询逻辑
                     rag/utils.py         # 工具函数

  ---
  二、目录结构优化
  
  当前结构

  agent_app/
  ├── nodes/           # 11个节点文件
  ├── tools/           # 5个工具文件
  ├── rag/             # 3个文件
  ├── file_inputs/     # 2个文件
  ├── utils/           # 仅1个文件
  └── 12个模块文件

  建议结构

  agent_app/
  ├── core/                    # 核心逻辑
  │   ├── __init__.py
  │   ├── state.py
  │   ├── graph.py
  │   └── orchestrator.py
  ├── nodes/                   # 节点
  │   ├── __init__.py
  │   ├── agent.py
  │   ├── planning.py
  │   ├── reflection.py
  │   └── ...
  ├── tools/                   # 工具
  │   ├── __init__.py
  │   ├── runtime.py
  │   ├── registry.py
  │   └── ...
  ├── rag/                     # RAG
  │   ├── __init__.py
  │   ├── store.py
  │   └── query.py
  ├── cli/                     # CLI 相关（新目录）
  │   ├── __init__.py
  │   ├── app.py              # 主入口
  │   ├── commands.py          # 命令处理
  │   ├── stream.py           # 流式输出
  │   └── cancel.py           # 取消控制
  ├── file_inputs/            # 文件输入
  │   └── parser.py
  ├── utils/                  # 工具函数
  │   ├── __init__.py
  │   ├── messages.py
  │   └── regex.py            # 共享正则表达式
  └── config.py

  ---
  三、代码重复问题（必须修复）
  
  问题1：伪工具调用正则表达式重复定义

  以下文件各自独立定义了相同的正则表达式：
  - agent_app/nodes/agent.py
  - agent_app/cli/stream.py
  - agent_app/nodes/response.py
  
  解决方案：创建 agent_app/utils/regex.py

  """共享正则表达式模式。"""

  import re

  # 伪工具调用模式
  PSEUDO_TOOL_CALL_BLOCK_PATTERN = re.compile(
      r"<tool_call\b[^>]*>.*?</tool_call>", re.IGNORECASE | re.DOTALL
  )
  PSEUDO_TOOL_CALL_START_PATTERN = re.compile(
      r"<tool_call\b[^>]*>", re.IGNORECASE
  )
  PSEUDO_PARAMETER_PATTERN = re.compile(
      r"<parameter=([^>\s]+)>(.*?)</parameter>", re.IGNORECASE | re.DOTALL
  )
  PSEUDO_TOOL_MARKERS = ("<tool_call", "</tool_call", "<function=",
  "</function", "<parameter", "</parameter")

  ---
  四、功能拆分建议
  
  1. 会话管理模块独立化

  当前 cli.py 中会话管理逻辑应该独立为 session_manager.py：

  # agent_app/session_manager.py
  class SessionManager:
      """会话管理器。"""

      def __init__(self):
          self.current_session = None
          self.state = None
  
      def create_session(self, session_id=None):
          """创建新会话。"""
          ...

      def save_session(self):
          """保存会话。"""
          ...

      def load_session(self, session_id):
          """加载会话。"""
          ...

      def list_sessions(self):
          """列出所有会话。"""
          ...

  2. 命令处理器独立化

  将 /sessions、/resume、/new 等命令提取为独立模块：

  # agent_app/cli_commands.py
  class CommandHandler:
      """CLI 命令处理器。"""

      def __init__(self, session_manager, rag_manager):
          self.session_manager = session_manager
          self.rag_manager = rag_manager

      def handle_command(self, command: str) -> bool:
          """处理命令，返回是否已处理。"""
          ...

      def cmd_sessions(self):
          """处理 /sessions 命令。"""
          ...

      def cmd_resume(self, session_id):
          """处理 /resume 命令。"""
          ...

  3. 工具执行器重构

  将 tools/runtime.py 拆分为：

  # tools/registry.py
  class ToolRegistry:
      """工具注册表。"""
  
      def register(self, name: str, func: Callable, metadata: ToolMetadata):
          ...

      def get(self, name: str) -> Optional[Tool]:
          ...

  # tools/executor.py
  class ToolExecutor:
      """工具执行器。"""

      def __init__(self, registry: ToolRegistry):
          self.registry = registry

      def execute(self, tool_name: str, args: dict) -> ToolResult:
          ...

  ---
  五、依赖优化建议
  
  1. 降低 nodes/agent.py 的耦合度

  该文件导入了 11 个模块，建议：
  - 将规划相关逻辑移至 nodes/planning.py
  - 将工具选择相关逻辑移至 tool_selector.py
  - 只保留核心的 Agent 执行逻辑
  
  2. 统一配置访问方式

  当前每个模块都直接导入 config.py 中的具体变量，建议：

  # agent_app/config.py
  class AppConfig:
      """应用配置单例。"""
      _instance = None

      @classmethod
      def get(cls):
          if cls._instance is None:
              cls._instance = cls()
          return cls._instance

      @property
      def cli_stream(self):
          return os.getenv("CLI_STREAM", "true").lower() == "true"

  # 使用方式
  from agent_app.config import AppConfig
  config = AppConfig.get()
  if config.cli_stream:
      ...

  ---
  六、优先级建议
  
  ┌────────┬────────────────────────────┬────────┬──────────────┐
  │ 优先级 │           优化项           │ 工作量 │     影响     │
  ├────────┼────────────────────────────┼────────┼──────────────┤
  │ 高     │ 修复代码重复（正则表达式） │ 0.5天  │ 提升维护性   │
  ├────────┼────────────────────────────┼────────┼──────────────┤
  │ 高     │ 拆分 cli.py                │ 1天    │ 降低复杂度   │
  ├────────┼────────────────────────────┼────────┼──────────────┤
  │ 中     │ 重构目录结构               │ 2-3天  │ 提升组织性   │
  ├────────┼────────────────────────────┼────────┼──────────────┤
  │ 中     │ 独立会话管理               │ 1天    │ 提升可测试性 │
  ├────────┼────────────────────────────┼────────┼──────────────┤
  │ 低     │ 降低模块耦合               │ 2天    │ 长期维护     │
  └────────┴────────────────────────────┴────────┴──────────────┘

  ---
  总结：项目结构整体合理，但有几个明显的优化点：
  1. 代码重复是最紧急的问题，应立即修复
  2. cli.py 承担了太多职责，应该拆分
  3. 目录结构可以进一步细化，特别是 CLI 相关代码
  4. 会话管理逻辑应该独立为专门的模块
