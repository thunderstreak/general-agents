"""检查意图分类 prompt 样例。"""

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_app.intent import classify_intent
from agent_app.prompt_loader import PROMPT_DIR


def main() -> int:
    """运行意图分类样例检查。"""
    examples_path = PROMPT_DIR / "intent_classifier.examples.json"
    examples = json.loads(examples_path.read_text(encoding="utf-8"))
    failures = []

    for example in examples:
        decision = classify_intent(example["input"])
        expected_intent = example["expected_intent"]
        min_confidence = example.get("min_confidence", 0.0)
        passed = decision.intent == expected_intent and decision.confidence >= min_confidence

        status = "PASS" if passed else "FAIL"
        print(
            f"{status} | input={example['input']} | "
            f"expected={expected_intent} | actual={decision.intent} | "
            f"confidence={decision.confidence:.2f} | reason={decision.reason}"
        )

        if not passed:
            failures.append(example["input"])

    if failures:
        print(f"\n意图分类样例检查失败：{len(failures)} 条", file=sys.stderr)
        return 1

    print("\n意图分类样例检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
