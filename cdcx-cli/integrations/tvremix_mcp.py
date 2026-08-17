"""tvremix.ai MCP (Model Context Protocol) client.

tvremix.ai ("TradingView Remix: AI Chart Copilot") exposes an MCP server at
``https://tvremix.xyz/api/mcp/v1``. MCP is a JSON-RPC 2.0 protocol, not a
plain REST API, so this wraps the handshake + tool-discovery + tool-call
sequence defined by the MCP spec's Streamable HTTP transport, letting
cdcx-cli list and invoke whatever tools the server exposes (chart analysis,
alerts, etc.) instead of hard-coding a specific tool contract.

Reference: https://modelcontextprotocol.io/specification (2025-06-18,
Streamable HTTP transport) -- a single POST endpoint that accepts JSON-RPC
requests/notifications and replies with either a plain ``application/json``
body or a ``text/event-stream`` of JSON-RPC messages.

Protocol flow used here:
  1. POST ``initialize`` (declares protocol version + client info). The
     server may return an ``Mcp-Session-Id`` response header, which is then
     echoed back on every subsequent request.
  2. POST the ``notifications/initialized`` notification (no response body
     expected -- servers typically reply ``202 Accepted``).
  3. POST ``tools/list`` / ``tools/call`` as needed.

Note: outbound access to ``tvremix.xyz`` is blocked from the environment
this was written in, so this client is built strictly against the public
MCP spec and unit-tested against a fake transport (see
``tests/test_tvremix_mcp.py``) -- it has not been smoke-tested against the
live endpoint. Run ``python cli.py mcp list-tools`` once in your own
environment to confirm connectivity/auth (and discover the real tool
names/schemas) before relying on it.
"""
import itertools
import json

import requests

DEFAULT_MCP_URL = "https://tvremix.xyz/api/mcp/v1"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "cdcx-cli"
CLIENT_VERSION = "0.1"


class MCPError(RuntimeError):
    """Raised for MCP transport failures or JSON-RPC error responses."""


class MCPClient:
    """Minimal MCP client over the Streamable HTTP transport."""

    def __init__(self, url=DEFAULT_MCP_URL, api_key=None, timeout=15, session=None):
        self.url = url
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()
        self._session_id = None
        self._ids = itertools.count(1)
        self._initialized = False
        self.server_info = None

    def initialize(self):
        """Perform the MCP initialize handshake (once per client instance)."""
        if self._initialized:
            return self.server_info

        self.server_info = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
        })
        self._initialized = True
        self._notify("notifications/initialized")
        return self.server_info

    def list_tools(self):
        """Return the list of tool descriptors (``{"name", "description", ...}``) the server exposes."""
        self.initialize()
        result = self._request("tools/list", {})
        return result.get("tools", [])

    def call_tool(self, name, arguments=None):
        """Call a tool by name. Returns the tool's ``content`` payload."""
        self.initialize()
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        if result.get("isError"):
            raise MCPError(f"Tool {name!r} returned an error: {result.get('content')}")
        return result.get("content", result)

    def _headers(self):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(self, payload):
        try:
            response = self.session.post(
                self.url, json=payload, headers=self._headers(), timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise MCPError(f"Request to {self.url} failed: {exc}") from exc

        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id

        if response.status_code == 202:
            return None  # notification acknowledged, no JSON-RPC response expected

        if response.status_code >= 400:
            raise MCPError(
                f"MCP server returned HTTP {response.status_code} for {self.url}: {response.text[:500]}"
            )

        return _parse_body(response)

    def _request(self, method, params):
        msg_id = next(self._ids)
        body = self._post({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
        if body is None:
            raise MCPError(f"No response body for MCP method {method!r}")

        message = _select_response(body, msg_id)
        if "error" in message:
            err = message["error"]
            raise MCPError(f"MCP error {err.get('code')} calling {method!r}: {err.get('message')}")
        return message.get("result", {})

    def _notify(self, method, params=None):
        # Notifications carry no "id" and get no JSON-RPC response (spec: 202 Accepted).
        self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})


def _parse_body(response):
    content_type = response.headers.get("Content-Type", "")
    if "text/event-stream" in content_type:
        return list(_iter_sse_json(response.text))

    text = response.text.strip()
    if not text:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise MCPError(f"Could not parse MCP response as JSON: {exc}") from exc


def _iter_sse_json(text):
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            data = line[len("data:"):].strip()
            if data and data != "[DONE]":
                yield json.loads(data)


def _select_response(body, msg_id):
    """``body`` is a single JSON-RPC message, or (SSE) a list of them -- pick the one matching msg_id."""
    if isinstance(body, list):
        for message in body:
            if message.get("id") == msg_id:
                return message
        raise MCPError(f"No response found for request id {msg_id} in: {body}")
    return body
