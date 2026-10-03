"""
telegram_inbox_http.py
----------------------
Opt-in Streamable-HTTP transport for the read-only Telegram inbox MCP server
(cdcx.telegram_inbox_mcp), for an MCP tunnel or another client that needs a
URL instead of a stdio command:

    ChatGPT -> OpenAI Secure MCP Tunnel -> tunnel-client (outbound only)
            -> http://127.0.0.1:8765/mcp  (this module)  -> InboxReader (SQLite, read-only)

It serves exactly the same five read-only tools as the stdio server -- the
MCP `server` object is imported from cdcx.telegram_inbox_mcp, not rebuilt --
and adds only:

    GET  /healthz   unauthenticated liveness: {"status": "ok", "inbox": "present"|"missing", ...}
    *    /mcp       the MCP endpoint; needs  Authorization: Bearer <CDCX_INBOX_MCP_AUTH_TOKEN>

Safety:
  * binds loopback only (127.0.0.1 / ::1 / localhost); any other --host is refused,
    so nothing is reachable from the network -- the tunnel connects out from here;
  * refuses to start without a bearer token of at least 32 characters, read from
    CDCX_INBOX_MCP_AUTH_TOKEN or --token-file (never from cdcx-cli/.env, which holds
    the Telegram credentials this process must never load); compared in constant time;
  * no Telegram access, no static files, no filesystem routes: every other path is 404.

Run:  CDCX_INBOX_MCP_AUTH_TOKEN=... python -m cdcx.telegram_inbox_http [--port 8765]
Make a token:  python -m cdcx.telegram_inbox_http --new-token
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Optional

from . import telegram_inbox_mcp as inbox_mcp

TOKEN_ENV = "CDCX_INBOX_MCP_AUTH_TOKEN"
MIN_TOKEN_LENGTH = 32
DEFAULT_PORT = 8765
MCP_PATH = "/mcp"
HEALTH_PATH = "/healthz"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class ConfigError(RuntimeError):
    pass


async def _send_json(send, status: int, body: dict, headers: tuple = ()) -> None:
    payload = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(payload)).encode()), *headers]})
    await send({"type": "http.response.body", "body": payload})


class InboxHTTPApp:
    """ASGI app: /healthz is open, /mcp needs the bearer token, anything else is 404."""

    def __init__(self, mcp_app, auth_token: str):
        self.mcp_app = mcp_app
        self._token = auth_token.encode()

    def _authorized(self, scope) -> bool:
        header = dict(scope.get("headers") or []).get(b"authorization", b"")
        scheme, _, given = header.partition(b" ")
        return scheme.lower() == b"bearer" and hmac.compare_digest(given.strip(), self._token)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":  # starts/stops the MCP session manager
            return await self.mcp_app(scope, receive, send)
        if scope["type"] != "http":
            return await _send_json(send, 404, {"error": "not found"})  # no websockets
        path = scope.get("path", "")
        if path == HEALTH_PATH and scope.get("method") in ("GET", "HEAD"):
            return await _send_json(send, 200, health())
        if path not in (MCP_PATH, MCP_PATH + "/"):
            return await _send_json(send, 404, {"error": "not found"})
        if not self._authorized(scope):
            return await _send_json(send, 401, {"error": "missing or invalid bearer token"},
                                    ((b"www-authenticate", b'Bearer realm="cdcx-telegram-inbox"'),))
        return await self.mcp_app(scope, receive, send)


def health() -> dict:
    return {"status": "ok", "server": "cdcx-telegram-inbox", "transport": "streamable-http",
            "read_only": True, "inbox": "present" if inbox_mcp.reader.path.exists() else "missing"}


def build_app(auth_token: str, host: str = "127.0.0.1") -> InboxHTTPApp:
    check_token(auth_token)
    # Stateless JSON responses: each tunnel request stands alone, no server-side sessions to expire.
    mcp_app = inbox_mcp.server.streamable_http_app(streamable_http_path=MCP_PATH, stateless_http=True,
                                         json_response=True, host=host)
    return InboxHTTPApp(mcp_app, auth_token)


def check_token(auth_token: Optional[str]) -> str:
    if not auth_token or len(auth_token.strip()) < MIN_TOKEN_LENGTH:
        raise ConfigError(f"set {TOKEN_ENV} (or --token-file) to a random secret of at least "
                          f"{MIN_TOKEN_LENGTH} characters; make one with --new-token")
    return auth_token.strip()


def check_host(host: str) -> str:
    if host not in LOOPBACK_HOSTS:
        raise ConfigError(f"refusing to bind {host!r}: this server only listens on loopback "
                          f"({', '.join(sorted(LOOPBACK_HOSTS))}); expose it through the MCP tunnel instead")
    return host


def load_token(token_file: Optional[str] = None, env: Optional[dict] = None) -> str:
    if token_file:
        return check_token(Path(token_file).read_text())
    return check_token((os.environ if env is None else env).get(TOKEN_ENV))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cdcx.telegram_inbox_http",
                                     description="Read-only Telegram inbox MCP over localhost HTTP (bearer token).")
    parser.add_argument("--host", default="127.0.0.1", help="loopback only (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--token-file", help=f"read the bearer token from this file instead of {TOKEN_ENV}")
    parser.add_argument("--new-token", action="store_true", help="print a fresh random token and exit")
    args = parser.parse_args(argv)
    if args.new_token:
        print(secrets.token_urlsafe(32))
        return 0
    try:
        host = check_host(args.host)
        app = build_app(load_token(args.token_file), host=host)
    except (ConfigError, OSError) as exc:
        print(f"not started: {exc}", file=sys.stderr)
        return 1
    import uvicorn

    print(f"cdcx telegram inbox MCP (read-only) on http://{host}:{args.port}{MCP_PATH}  "
          f"health: {HEALTH_PATH}  inbox: {inbox_mcp.reader.path}", file=sys.stderr, flush=True)
    uvicorn.run(app, host=host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
