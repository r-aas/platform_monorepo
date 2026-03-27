#!/usr/bin/env python3
"""Agent sandbox entrypoint.

Reads task from /task/config.json, executes via LLM with tool use,
and prints the result as JSON on the last line of stdout.
"""

import json
import os
import subprocess
import sys

TASK_PATH = "/task/config.json"


def load_task() -> dict:
    """Load the task configuration."""
    if not os.path.exists(TASK_PATH):
        return {"message": "No task config found", "system_prompt": "You are a helpful assistant."}
    with open(TASK_PATH) as f:
        return json.load(f)


def run_task_simple(task: dict) -> dict:
    """Execute task using direct LLM API call with tool use loop.

    This is a minimal implementation that:
    1. Sends the system prompt + message to the LLM
    2. If the LLM returns tool_calls, executes them (bash only for now)
    3. Feeds results back until no more tool_calls
    """
    import urllib.request

    base_url = os.environ.get("OPENAI_BASE_URL", "http://localhost:4000/v1")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("OPENAI_MODEL", "qwen2.5:14b")

    system_prompt = task.get("system_prompt", "You are a helpful assistant.")
    message = task.get("message", "")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "bash",
                "description": "Execute a bash command and return its output.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The bash command to execute."},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path relative to workspace."},
                        "content": {"type": "string", "description": "File content."},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file's content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path relative to workspace."},
                    },
                    "required": ["path"],
                },
            },
        },
    ]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]

    max_iterations = 20
    for iteration in range(max_iterations):
        print(f"[sandbox] iteration {iteration + 1}/{max_iterations}", file=sys.stderr)

        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
        }

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers=headers,
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            return {"error": f"LLM API error: {e}", "iteration": iteration}

        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        messages.append(msg)

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            # No more tool calls — return the final message
            return {"output": msg.get("content", ""), "iterations": iteration + 1}

        # Execute tool calls
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            result = execute_tool(name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result,
            })

    return {"error": "Max iterations reached", "iterations": max_iterations}


def execute_tool(name: str, args: dict) -> str:
    """Execute a tool and return the result as a string."""
    if name == "bash":
        command = args.get("command", "")
        print(f"[sandbox] bash: {command}", file=sys.stderr)
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=60,
                cwd="/home/agent/workspace",
            )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            if result.returncode != 0:
                output += f"\nExit code: {result.returncode}"
            return output[:10000]
        except subprocess.TimeoutExpired:
            return "Command timed out after 60 seconds"
        except Exception as e:
            return f"Error: {e}"

    elif name == "write_file":
        path = args.get("path", "")
        content = args.get("content", "")
        full_path = os.path.join("/home/agent/workspace", path)
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as f:
                f.write(content)
            return f"Written {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    elif name == "read_file":
        path = args.get("path", "")
        full_path = os.path.join("/home/agent/workspace", path)
        try:
            with open(full_path) as f:
                return f.read()[:50000]
        except Exception as e:
            return f"Error reading file: {e}"

    return f"Unknown tool: {name}"


def main():
    task = load_task()
    print(f"[sandbox] Starting task: {task.get('message', '')[:100]}", file=sys.stderr)

    result = run_task_simple(task)

    # Print result as JSON on the last line (gateway reads this)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
