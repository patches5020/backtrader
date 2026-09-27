"""
Build one paste-ready file for ChatGPT: .ai/HANDOFF/packet_for_chatgpt.md

Refreshes .ai/SHARED/system_state.json (git commit, branch, time, optional
test count), runs validate_handoff.py, then bundles the state, protected
parameters, strategy spec, recent change log and Claude's latest result.

Usage (from backtrader-repo):
    python .ai/prepare_handoff.py           # fast
    python .ai/prepare_handoff.py --tests   # also run the cdcx-cli test suite
"""
from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent
REPO = AI_DIR.parent


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()


def refresh_state(run_tests: bool) -> dict:
    state_path = AI_DIR / "SHARED" / "system_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    state.update({
        "updated": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "repo": "patches5020/backtrader",
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": _git("rev-parse", "--short", "HEAD"),
        "commit_subject": _git("log", "-1", "--format=%s"),
        "uncommitted_files": len([l for l in _git("status", "--porcelain").splitlines() if l.strip()]),
    })
    if run_tests:
        out = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=REPO / "cdcx-cli",
                             capture_output=True, text=True).stdout.strip().splitlines()
        summary = out[-1] if out else ""
        state["tests"] = {
            "passed": int(m.group(1)) if (m := re.search(r"(\d+) passed", summary)) else 0,
            "failed": int(m.group(1)) if (m := re.search(r"(\d+) failed", summary)) else 0,
            "as_of_commit": state["commit"],
        }
    state_path.write_text(json.dumps(state, indent=2) + "\n")
    return state


def main() -> int:
    state = refresh_state("--tests" in sys.argv)
    validation = subprocess.run([sys.executable, str(AI_DIR / "validate_handoff.py")],
                                capture_output=True, text=True).stdout.strip()
    params = json.loads((AI_DIR / "SHARED" / "risk_parameters.json").read_text())["parameters"]
    change_log = (AI_DIR / "SHARED" / "change_log.md").read_text().split("\n## ")
    recent = "\n## ".join(change_log[:3])  # header + the two most recent dates

    lines = [
        "# cdcx handoff packet for ChatGPT",
        "",
        "Paste this whole file into ChatGPT. To send Claude a task back, reply with a filled-in",
        "`chatgpt_to_claude.json` (format at the end).",
        "",
        "## System state",
        "```json", json.dumps(state, indent=2), "```",
        "",
        "## Validation",
        "```", validation, "```",
        "",
        "## Protected parameters (checked against the live code; change only with the user's approval)",
        "| Parameter | Value | Meaning |", "|---|---|---|",
        *[f"| {k} | {v['value']} | {v['meaning']} |" for k, v in params.items()],
        "",
        (AI_DIR / "SHARED" / "strategy_spec.md").read_text(),
        "",
        recent,
        "",
        "## Claude's latest result (claude_to_chatgpt.json)",
        "```json", (AI_DIR / "HANDOFF" / "claude_to_chatgpt.json").read_text().strip(), "```",
        "",
        "## Task format for Claude (chatgpt_to_claude.json)",
        "```json", (AI_DIR / "HANDOFF" / "chatgpt_to_claude.json").read_text().strip(), "```",
    ]
    out = AI_DIR / "HANDOFF" / "packet_for_chatgpt.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"Wrote {out.relative_to(REPO)}")
    print(validation.splitlines()[-1] if validation else "validation produced no output")
    return 0 if "PASS" in validation else 1


if __name__ == "__main__":
    raise SystemExit(main())
