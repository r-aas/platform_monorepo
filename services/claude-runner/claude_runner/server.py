#!/usr/bin/env python3
"""Agent Runner — HTTP trigger for headless AI agent sessions.

Runs on the Mac host. n8n (in k3d) calls this to spawn autonomous sessions
with Claude Code, OpenClaw, or any CLI-based agent.

Endpoints:
    POST /run       — Start a new agent session (async, returns run ID)
    GET  /run/{id}  — Poll run status + output
    GET  /runs      — List recent runs
    POST /cancel/{id} — Cancel a running session
    GET  /health    — Health check
    GET  /runtimes  — List available agent runtimes
"""

from __future__ import annotations

import asyncio
import os
import signal
import shutil
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_WORK_DIR = os.getenv("AGENT_WORK_DIR", str(Path.home() / "work"))
MAX_CONCURRENT = int(os.getenv("AGENT_MAX_CONCURRENT", "1"))
LOG_DIR = Path(os.getenv("AGENT_LOG_DIR", str(Path.home() / ".claude" / "runner-logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Agent Runtimes — pluggable CLI agent backends
# ---------------------------------------------------------------------------

@dataclass
class AgentRuntime:
    name: str
    description: str
    bin_path: str
    available: bool = False

    def build_cmd(self, req: "RunRequest") -> list[str]:
        raise NotImplementedError


class ClaudeRuntime(AgentRuntime):
    """Claude Code CLI — anthropic's coding agent."""

    def __init__(self):
        bin_path = os.getenv("CLAUDE_BIN", "/opt/homebrew/bin/claude")
        super().__init__(
            name="claude",
            description="Claude Code CLI — autonomous coding agent",
            bin_path=bin_path,
            available=Path(bin_path).exists(),
        )

    def build_cmd(self, req: RunRequest) -> list[str]:
        cmd = [
            self.bin_path,
            "--print",
            "--output-format", "text",
            "--model", req.model or "sonnet",
            "--permission-mode", req.permission_mode or "bypassPermissions",
            "--verbose",
        ]

        if req.max_budget_usd:
            cmd.extend(["--max-budget-usd", str(req.max_budget_usd)])

        if req.allowed_tools:
            cmd.extend(["--allowed-tools", ",".join(req.allowed_tools)])

        if req.add_dirs:
            for d in req.add_dirs:
                cmd.extend(["--add-dir", d])

        if req.system_prompt_append:
            cmd.extend(["--append-system-prompt", req.system_prompt_append])

        if req.mcp_config:
            cmd.extend(["--mcp-config", req.mcp_config])

        if req.skills_dir:
            cmd.extend(["--plugin-dir", req.skills_dir])

        cmd.append(req.prompt)
        return cmd


class OpenClawRuntime(AgentRuntime):
    """OpenClaw — open-source coding agent (Claude Code compatible)."""

    def __init__(self):
        # Check common install locations
        bin_path = os.getenv("OPENCLAW_BIN", "")
        if not bin_path:
            for candidate in [
                str(Path.home() / ".local" / "bin" / "openclaw"),
                "/opt/homebrew/bin/openclaw",
                shutil.which("openclaw") or "",
            ]:
                if candidate and Path(candidate).exists():
                    bin_path = candidate
                    break
            if not bin_path:
                bin_path = "openclaw"

        super().__init__(
            name="openclaw",
            description="OpenClaw — open-source coding agent",
            bin_path=bin_path,
            available=bool(shutil.which(bin_path) or Path(bin_path).exists()),
        )

    def build_cmd(self, req: RunRequest) -> list[str]:
        cmd = [
            self.bin_path,
            "--print",
            "--output-format", "text",
        ]

        if req.model:
            cmd.extend(["--model", req.model])

        if req.permission_mode:
            cmd.extend(["--permission-mode", req.permission_mode])

        if req.max_budget_usd:
            cmd.extend(["--max-budget-usd", str(req.max_budget_usd)])

        if req.allowed_tools:
            cmd.extend(["--allowed-tools", ",".join(req.allowed_tools)])

        if req.add_dirs:
            for d in req.add_dirs:
                cmd.extend(["--add-dir", d])

        if req.system_prompt_append:
            cmd.extend(["--append-system-prompt", req.system_prompt_append])

        if req.mcp_config:
            cmd.extend(["--mcp-config", req.mcp_config])

        if req.skills_dir:
            cmd.extend(["--plugin-dir", req.skills_dir])

        cmd.append(req.prompt)
        return cmd


class GenericCLIRuntime(AgentRuntime):
    """Generic CLI agent — wraps any command-line tool."""

    def __init__(self):
        super().__init__(
            name="generic",
            description="Generic CLI agent — run any command",
            bin_path="bash",
            available=True,
        )

    def build_cmd(self, req: RunRequest) -> list[str]:
        # For generic, the prompt IS the command
        return ["bash", "-c", req.prompt]


# Registry of available runtimes
RUNTIMES: dict[str, AgentRuntime] = {}


def _init_runtimes():
    for cls in [ClaudeRuntime, OpenClawRuntime, GenericCLIRuntime]:
        rt = cls()
        RUNTIMES[rt.name] = rt


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


@dataclass
class RunRecord:
    id: str
    prompt: str
    runtime: str
    status: RunStatus
    work_dir: str
    model: str
    started_at: float
    finished_at: float | None = None
    exit_code: int | None = None
    output: str = ""
    error: str = ""
    process: asyncio.subprocess.Process | None = field(default=None, repr=False)


# In-memory store — last 50 runs
runs: dict[str, RunRecord] = {}
run_semaphore: asyncio.Semaphore | None = None

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Agent Runner", version="0.2.0")


@app.on_event("startup")
async def startup():
    global run_semaphore
    run_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    _init_runtimes()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    prompt: str = "/continue"
    runtime: str = "claude"
    work_dir: str = DEFAULT_WORK_DIR
    model: str = ""
    max_turns: int = 200
    max_budget_usd: float | None = 5.0
    allowed_tools: list[str] | None = None
    permission_mode: str | None = "bypassPermissions"
    add_dirs: list[str] | None = None
    system_prompt_append: str | None = None
    mcp_config: str | None = None
    skills_dir: str | None = None
    env: dict[str, str] | None = None


class RunResponse(BaseModel):
    id: str
    runtime: str
    status: RunStatus
    message: str


class RunDetail(BaseModel):
    id: str
    prompt: str
    runtime: str
    status: RunStatus
    work_dir: str
    model: str
    started_at: float
    finished_at: float | None
    exit_code: int | None
    output: str
    error: str
    duration_seconds: float | None


# ---------------------------------------------------------------------------
# Core: spawn agent process
# ---------------------------------------------------------------------------


async def _run_agent(record: RunRecord, req: RunRequest):
    assert run_semaphore is not None
    async with run_semaphore:
        record.status = RunStatus.running

        rt = RUNTIMES.get(req.runtime)
        if not rt:
            record.status = RunStatus.failed
            record.error = f"Unknown runtime: {req.runtime}"
            record.finished_at = time.time()
            return

        if not rt.available:
            record.status = RunStatus.failed
            record.error = f"Runtime '{req.runtime}' not available (binary not found: {rt.bin_path})"
            record.finished_at = time.time()
            return

        cmd = rt.build_cmd(req)
        log_file = LOG_DIR / f"{record.id}.log"

        # Build environment
        env = {**os.environ}
        if req.runtime == "claude":
            env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        if req.env:
            env.update(req.env)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=req.work_dir,
                env=env,
            )
            record.process = proc

            stdout, stderr = await proc.communicate()

            record.output = stdout.decode(errors="replace")
            record.error = stderr.decode(errors="replace")
            record.exit_code = proc.returncode
            record.status = RunStatus.completed if proc.returncode == 0 else RunStatus.failed

        except asyncio.CancelledError:
            record.status = RunStatus.cancelled
            if record.process and record.process.returncode is None:
                record.process.send_signal(signal.SIGTERM)
                await asyncio.sleep(2)
                if record.process.returncode is None:
                    record.process.kill()
        except Exception as e:
            record.status = RunStatus.failed
            record.error = str(e)
        finally:
            record.finished_at = time.time()
            record.process = None

            # Persist log
            with open(log_file, "w") as f:
                f.write(f"# Agent Runner Log — {record.id}\n")
                f.write(f"# Runtime: {record.runtime}\n")
                f.write(f"# Prompt: {record.prompt}\n")
                f.write(f"# Model: {record.model}\n")
                f.write(f"# Status: {record.status}\n")
                f.write(f"# Exit code: {record.exit_code}\n")
                f.write(f"# Duration: {record.finished_at - record.started_at:.1f}s\n\n")
                f.write("=== STDOUT ===\n")
                f.write(record.output)
                f.write("\n=== STDERR ===\n")
                f.write(record.error)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/run", response_model=RunResponse)
async def start_run(req: RunRequest):
    # Validate runtime
    if req.runtime not in RUNTIMES:
        raise HTTPException(400, f"Unknown runtime '{req.runtime}'. Available: {list(RUNTIMES.keys())}")

    # Enforce max concurrent
    active = sum(1 for r in runs.values() if r.status in (RunStatus.queued, RunStatus.running))
    if active >= MAX_CONCURRENT:
        raise HTTPException(429, f"Max concurrent runs ({MAX_CONCURRENT}) reached. Try again later.")

    run_id = uuid.uuid4().hex[:12]
    record = RunRecord(
        id=run_id,
        prompt=req.prompt,
        runtime=req.runtime,
        status=RunStatus.queued,
        work_dir=req.work_dir,
        model=req.model,
        started_at=time.time(),
    )
    runs[run_id] = record

    # Prune old runs (keep last 50)
    if len(runs) > 50:
        oldest = sorted(runs.values(), key=lambda r: r.started_at)
        for old in oldest[: len(runs) - 50]:
            if old.status not in (RunStatus.queued, RunStatus.running):
                runs.pop(old.id, None)

    # Fire and forget
    asyncio.create_task(_run_agent(record, req))

    return RunResponse(id=run_id, runtime=req.runtime, status=RunStatus.queued, message="Run queued")


@app.get("/run/{run_id}", response_model=RunDetail)
async def get_run(run_id: str):
    record = runs.get(run_id)
    if not record:
        raise HTTPException(404, "Run not found")

    duration = None
    if record.finished_at:
        duration = record.finished_at - record.started_at
    elif record.status == RunStatus.running:
        duration = time.time() - record.started_at

    return RunDetail(
        id=record.id,
        prompt=record.prompt,
        runtime=record.runtime,
        status=record.status,
        work_dir=record.work_dir,
        model=record.model,
        started_at=record.started_at,
        finished_at=record.finished_at,
        exit_code=record.exit_code,
        output=record.output[-10000:],  # Last 10k chars
        error=record.error[-5000:],
        duration_seconds=duration,
    )


@app.get("/runs")
async def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    sorted_runs = sorted(runs.values(), key=lambda r: r.started_at, reverse=True)[:limit]
    return [
        {
            "id": r.id,
            "prompt": r.prompt[:100],
            "runtime": r.runtime,
            "status": r.status,
            "model": r.model,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "exit_code": r.exit_code,
            "duration": (r.finished_at - r.started_at) if r.finished_at else None,
        }
        for r in sorted_runs
    ]


@app.post("/cancel/{run_id}")
async def cancel_run(run_id: str):
    record = runs.get(run_id)
    if not record:
        raise HTTPException(404, "Run not found")
    if record.status not in (RunStatus.queued, RunStatus.running):
        return {"message": f"Run already {record.status}"}

    if record.process and record.process.returncode is None:
        record.process.send_signal(signal.SIGTERM)
        record.status = RunStatus.cancelled
        return {"message": "Cancelled (SIGTERM sent)"}

    record.status = RunStatus.cancelled
    return {"message": "Cancelled"}


@app.get("/runtimes")
async def list_runtimes() -> list[dict[str, Any]]:
    return [
        {
            "name": rt.name,
            "description": rt.description,
            "bin_path": rt.bin_path,
            "available": rt.available,
        }
        for rt in RUNTIMES.values()
    ]


@app.get("/health")
async def health():
    available_runtimes = {name: rt.available for name, rt in RUNTIMES.items()}
    any_available = any(available_runtimes.values())
    active = sum(1 for r in runs.values() if r.status in (RunStatus.queued, RunStatus.running))
    total = len(runs)
    return {
        "status": "ok" if any_available else "degraded",
        "runtimes": available_runtimes,
        "active_runs": active,
        "total_runs": total,
        "max_concurrent": MAX_CONCURRENT,
        "work_dir": DEFAULT_WORK_DIR,
        "log_dir": str(LOG_DIR),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7777)
