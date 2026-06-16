"""CLI 长期记忆命令处理。"""

from collections.abc import Callable
from dataclasses import dataclass

from agent_app.memory import MemoryStore


@dataclass(frozen=True)
class MemoryOperations:
    """Memory 命令依赖操作。"""

    list_memory: Callable[[], MemoryStore]
    delete_memory_item: Callable[[str], bool]
    clear_memory: Callable[[], None]


def handle_memory_command(arg: str, operations: MemoryOperations) -> None:
    """处理长期记忆命令。"""
    subcommand, _, value = arg.partition(" ")
    subcommand = subcommand.strip()
    value = value.strip()

    if subcommand == "list":
        _memory_list(operations)
        return

    if subcommand == "delete":
        if not value:
            print("用法：/memory delete <memory_id>\n")
            return
        _memory_delete(value, operations)
        return

    if subcommand == "clear":
        operations.clear_memory()
        print("已清空长期记忆。\n")
        return

    print("Memory 命令：/memory list、/memory delete <memory_id>、/memory clear\n")


def _memory_list(operations: MemoryOperations) -> None:
    """打印长期记忆列表。"""
    memory = operations.list_memory()
    if not memory.summary and not memory.items:
        print("暂无长期记忆。\n")
        return

    if memory.summary:
        print("历史摘要：")
        print(memory.summary)
        print()

    if memory.items:
        print("长期记忆：")
        for item in memory.items:
            print(f"- memory_id={item.id} | category={item.category} | created_at={item.created_at} | content={item.content}")
        print()
    else:
        print("没有可删除的长期记忆条目。\n")


def _memory_delete(memory_id: str, operations: MemoryOperations) -> None:
    """删除长期记忆。"""
    if operations.delete_memory_item(memory_id):
        print(f"已删除长期记忆：{memory_id}\n")
    else:
        print(f"长期记忆不存在：{memory_id}\n")
