"""
Validate the ChatGPT <-> Claude Code handoff layer.

1. Every protected value in .ai/SHARED/risk_parameters.json must equal what
   the LIVE cdcx code actually uses (imports cdcx and reads the attribute,
   so .env overrides are included). A mismatch FAILS -- either the code
   changed a protected parameter or the file is wrong; the user decides.
2. Both handoff JSON files must parse and carry their required fields.
3. A ChatGPT task that touches protected parameters is flagged loudly: it
   needs the user's explicit approval, not just the handoff.

Usage (from backtrader-repo):  python .ai/validate_handoff.py
Exit code 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations

import importlib
import json
import math
import sys
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent
REPO = AI_DIR.parent
REQUIRED = {
    "chatgpt_to_claude.json": {"task_id", "created", "status", "title", "request", "acceptance_criteria",
                               "touches_protected_parameters"},
    "claude_to_chatgpt.json": {"task_id", "completed", "status", "summary", "files_changed", "commits", "tests",
                               "protected_parameters_changed", "baseline_verdict_changed"},
}
STATUSES = {"empty", "open", "in_progress", "done", "blocked", "rejected"}


def _resolve(source: str):
    """"config.settings.tp_ratios" -> cdcx.config.settings.tp_ratios."""
    module_name, *attrs = source.split(".")
    obj = importlib.import_module(f"cdcx.{module_name}")
    for attr in attrs:
        obj = getattr(obj, attr)
    return obj


def _equal(expected, actual) -> bool:
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(float(expected), float(actual), rel_tol=1e-9)
    if isinstance(expected, list):
        return list(actual) == expected
    return expected == actual


def check_protected(errors: list[str]) -> None:
    sys.path.insert(0, str(REPO / "cdcx-cli"))
    spec = json.loads((AI_DIR / "SHARED" / "risk_parameters.json").read_text())
    for name, entry in spec["parameters"].items():
        try:
            actual = _resolve(entry["source"])
        except Exception as exc:  # a renamed/removed attribute is itself a finding
            errors.append(f"protected '{name}': cannot read {entry['source']} ({exc})")
            continue
        if _equal(entry["value"], actual):
            print(f"  ok   {name:<32} {actual!r}")
        else:
            errors.append(f"protected '{name}': file says {entry['value']!r}, code uses {actual!r} ({entry['source']})")


def check_handoffs(errors: list[str], warnings: list[str]) -> None:
    for filename, required in REQUIRED.items():
        path = AI_DIR / "HANDOFF" / filename
        try:
            data = json.loads(path.read_text())
        except Exception as exc:
            errors.append(f"{filename}: not valid JSON ({exc})")
            continue
        missing = required - data.keys()
        if missing:
            errors.append(f"{filename}: missing fields {sorted(missing)}")
        if data.get("status") not in STATUSES:
            errors.append(f"{filename}: status {data.get('status')!r} not one of {sorted(STATUSES)}")
        print(f"  ok   {filename} (status: {data.get('status')})" if not missing else f"  FAIL {filename}")
        if filename == "chatgpt_to_claude.json" and data.get("touches_protected_parameters"):
            warnings.append("ChatGPT task touches PROTECTED parameters -- needs the user's explicit approval "
                            "before any change; the handoff alone is not approval.")
        if filename == "claude_to_chatgpt.json" and data.get("protected_parameters_changed"):
            warnings.append("Claude's result reports a PROTECTED parameter change -- confirm the user approved it.")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    print("Protected parameters vs live cdcx code:")
    check_protected(errors)
    print("Handoff files:")
    check_handoffs(errors, warnings)
    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"AI handoff validation: {'FAIL' if errors else 'PASS'}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
