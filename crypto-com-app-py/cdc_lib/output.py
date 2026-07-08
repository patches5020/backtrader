"""Shared JSON output/exit helpers, ported from scripts/lib/output.ts."""
import json
import sys


class ErrorCode:
    MISSING_ENV = "MISSING_ENV"
    API_ERROR = "API_ERROR"
    INVALID_ARGS = "INVALID_ARGS"
    QUOTATION_FAILED = "QUOTATION_FAILED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    API_KEY_NOT_FOUND = "API_KEY_NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    UNKNOWN = "UNKNOWN"


class SkillExit(SystemExit):
    """Raised by success()/fail() so callers/tests can catch it instead of killing the process."""


def success(data):
    print(json.dumps({"ok": True, "data": data}, indent=2))
    raise SkillExit(0)


def fail(code, message):
    print(json.dumps({"ok": False, "error": code, "error_message": message}, indent=2))
    raise SkillExit(1)


def run(fn):
    """Run fn(), converting unexpected exceptions into a fail() JSON envelope."""
    try:
        fn()
    except SkillExit as exc:
        sys.exit(exc.code)
    except Exception as exc:  # noqa: BLE001 - mirrors the TS catch-all in run()
        fail(ErrorCode.UNKNOWN, str(exc))
