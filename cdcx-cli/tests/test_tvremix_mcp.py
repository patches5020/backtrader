import json as jsonlib

import pytest

from integrations.tvremix_mcp import MCPClient, MCPError, DEFAULT_MCP_URL


class FakeResponse:
    def __init__(self, payload=None, status_code=200, headers=None, raw_text=None):
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}
        self.text = raw_text if raw_text is not None else (jsonlib.dumps(payload) if payload is not None else "")

    def json(self):
        return jsonlib.loads(self.text) if self.text else None


class FakeSession:
    """Routes POSTed JSON-RPC messages to canned responses keyed by method name."""

    def __init__(self, responses, session_id="sess-123"):
        self.responses = responses
        self.session_id = session_id
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        method = json["method"]

        if method == "notifications/initialized":
            return FakeResponse(status_code=202)

        response = self.responses[method]
        if response.headers.get("Mcp-Session-Id") is None and method == "initialize":
            response.headers = dict(response.headers)
            response.headers["Mcp-Session-Id"] = self.session_id
        return response


def default_responses():
    return {
        "initialize": FakeResponse({
            "jsonrpc": "2.0", "id": 1,
            "result": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "serverInfo": {"name": "tvremix", "version": "1.0"}},
        }),
        "tools/list": FakeResponse({
            "jsonrpc": "2.0", "id": 2,
            "result": {"tools": [{"name": "chart_analyze", "description": "Analyze the active chart"}]},
        }),
        "tools/call": FakeResponse({
            "jsonrpc": "2.0", "id": 3,
            "result": {"content": [{"type": "text", "text": "BTCUSD is trending up"}], "isError": False},
        }),
    }


def make_client(responses=None, **kwargs):
    session = FakeSession(responses or default_responses())
    return MCPClient(session=session, **kwargs), session


def test_initialize_sends_expected_handshake_and_stores_session_id():
    client, session = make_client()
    result = client.initialize()

    assert result["serverInfo"]["name"] == "tvremix"
    init_call = session.calls[0]
    assert init_call["url"] == DEFAULT_MCP_URL
    assert init_call["json"]["method"] == "initialize"
    assert init_call["json"]["params"]["protocolVersion"] == "2025-06-18"

    # notifications/initialized must follow initialize per spec
    assert session.calls[1]["json"]["method"] == "notifications/initialized"
    assert "id" not in session.calls[1]["json"]

    # session id from the initialize response is echoed on the next request
    client.list_tools()
    assert session.calls[-1]["headers"]["Mcp-Session-Id"] == "sess-123"


def test_initialize_is_only_performed_once():
    client, session = make_client()
    client.list_tools()
    client.list_tools()
    init_calls = [c for c in session.calls if c["json"]["method"] == "initialize"]
    assert len(init_calls) == 1


def test_list_tools_returns_tool_descriptors():
    client, _ = make_client()
    tools = client.list_tools()
    assert tools == [{"name": "chart_analyze", "description": "Analyze the active chart"}]


def test_call_tool_returns_content():
    client, session = make_client()
    content = client.call_tool("chart_analyze", {"symbol": "BTCUSD"})
    assert content == [{"type": "text", "text": "BTCUSD is trending up"}]

    call = next(c for c in session.calls if c["json"]["method"] == "tools/call")
    assert call["json"]["params"] == {"name": "chart_analyze", "arguments": {"symbol": "BTCUSD"}}


def test_call_tool_raises_on_isError():
    responses = default_responses()
    responses["tools/call"] = FakeResponse({
        "jsonrpc": "2.0", "id": 3,
        "result": {"content": [{"type": "text", "text": "bad symbol"}], "isError": True},
    })
    client, _ = make_client(responses)
    with pytest.raises(MCPError, match="bad symbol"):
        client.call_tool("chart_analyze", {"symbol": "NOPE"})


def test_jsonrpc_error_response_raises_mcp_error():
    responses = default_responses()
    responses["tools/list"] = FakeResponse({
        "jsonrpc": "2.0", "id": 2, "error": {"code": -32601, "message": "Method not found"},
    })
    client, _ = make_client(responses)
    with pytest.raises(MCPError, match="Method not found"):
        client.list_tools()


def test_http_error_status_raises_mcp_error():
    responses = default_responses()
    responses["initialize"] = FakeResponse(status_code=403, raw_text="forbidden")
    client, _ = make_client(responses)
    with pytest.raises(MCPError, match="403"):
        client.initialize()


def test_sse_response_is_parsed():
    responses = default_responses()
    responses["tools/list"] = FakeResponse(
        headers={"Content-Type": "text/event-stream"},
        raw_text='data: {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}\n\n',
    )
    client, _ = make_client(responses)
    assert client.list_tools() == []


def test_api_key_sets_authorization_header():
    client, session = make_client(api_key="secret-token")
    client.initialize()
    assert session.calls[0]["headers"]["Authorization"] == "Bearer secret-token"


def test_custom_url_is_used():
    client, session = make_client(url="https://tvremix.xyz/api/mcp/v1-staging")
    client.initialize()
    assert session.calls[0]["url"] == "https://tvremix.xyz/api/mcp/v1-staging"
