#!/usr/bin/env python3
"""onto.py — call Open Ontologies MCP tools via cluster HTTP endpoint.

Usage:
    onto.py <tool> [key=value ...]
    onto.py onto_validate input=/path/to/file.ttl
    onto.py onto_load path=/path/to/file.ttl
    onto.py onto_stats
    onto.py onto_query query="SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"

Multiple tools (maintains session):
    onto.py onto_load path=a.ttl + onto_load path=b.ttl + onto_reason + onto_stats
"""
import json, sys, http.client
from urllib.parse import urlparse

URL = "http://open-ontologies.platform.127.0.0.1.nip.io/mcp"


def mcp_session(url, tool_calls):
    """Run MCP session: init → notify → tool calls. Returns tool results."""
    parsed = urlparse(url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=30)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    def post(body):
        conn.request("POST", parsed.path, json.dumps(body).encode(), headers)
        resp = conn.getresponse()
        # Extract session ID
        sid = resp.getheader("mcp-session-id")
        if sid:
            headers["Mcp-Session-Id"] = sid
        raw = resp.read().decode()
        for line in raw.split("\n"):
            if line.startswith("data: {"):
                return json.loads(line[6:])
        return {}

    # Initialize
    post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "onto-cli", "version": "1.0.0"}}})

    # Notification (no response expected but server may send one)
    post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    # Tool calls
    results = {}
    for i, (tool, args) in enumerate(tool_calls):
        resp = post({"jsonrpc": "2.0", "id": 100 + i,
                      "method": "tools/call",
                      "params": {"name": tool, "arguments": args}})
        results[i] = resp
    conn.close()
    return results


def parse_args(argv):
    calls = []
    tool, args = None, {}
    for arg in argv:
        if arg == "+":
            if tool:
                calls.append((tool, args))
            tool, args = None, {}
        elif tool is None:
            tool = arg
        elif "=" in arg:
            k, v = arg.split("=", 1)
            args[k] = v
        else:
            args[arg] = True
    if tool:
        calls.append((tool, args))
    return calls


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    calls = parse_args(sys.argv[1:])
    results = mcp_session(URL, calls)

    for i, (tool, _) in enumerate(calls):
        if len(calls) > 1:
            print(f"\n{'='*50}\n  {tool}\n{'='*50}")
        resp = results.get(i, {})
        content = resp.get("result", {}).get("content", [])
        if not content and "error" in resp:
            print(f"ERROR: {json.dumps(resp['error'], indent=2)}")
            continue
        for c in content:
            text = c.get("text", "")
            try:
                print(json.dumps(json.loads(text), indent=2))
            except (json.JSONDecodeError, ValueError):
                print(text)


if __name__ == "__main__":
    main()
