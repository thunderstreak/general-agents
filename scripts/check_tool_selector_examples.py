"""检查工具选择器样例。"""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_app.prompt_loader import PROMPT_DIR
from agent_app.tool_selector import select_tool


def main() -> int:
    """运行工具选择器样例检查。"""
    examples_path = PROMPT_DIR / "tool_selector.examples.json"
    examples = json.loads(examples_path.read_text(encoding="utf-8"))
    failures = []

    for example in examples:
        selection = select_tool(example["input"])
        expected_action = example["expected_action"]
        expected_tool_name = example["expected_tool_name"]
        min_confidence = example.get("min_confidence", 0.0)
        passed = (
            selection.action == expected_action
            and selection.tool_name == expected_tool_name
            and selection.confidence >= min_confidence
        )

        status = "PASS" if passed else "FAIL"
        print(
            f"{status} | input={example['input']} | "
            f"expected={expected_action}/{expected_tool_name} | "
            f"actual={selection.action}/{selection.tool_name} | "
            f"confidence={selection.confidence:.2f} | reason={selection.reason}"
        )

        if not passed:
            failures.append(example["input"])

    if failures:
        print(f"\n工具选择器样例检查失败：{len(failures)} 条", file=sys.stderr)
        return 1

    print("\n工具选择器样例检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
