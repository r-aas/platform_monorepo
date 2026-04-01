#!/usr/bin/env python3
"""AgentOps eval board — evals + CI/CD pipelines + readiness validation.

Three sections:
  1. Eval Table    — task × dataset × method × metric from MLflow
  2. Pipelines     — recent GitLab CI pipelines with stage-level status
  3. Agent Readiness — per-agent checklist (dataset? eval? baseline? pipeline? promoted?)

Usage:
    uv run scripts/eval-board.py
    uv run scripts/eval-board.py --port 8080 --refresh 30
"""
# /// script
# requires-python = ">=3.12"
# dependencies = ["fastapi>=0.115", "uvicorn>=0.34", "httpx>=0.28"]
# ///

import argparse
import os
import time
from datetime import datetime, timezone

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="eval-board")

# ── Config (overridable via CLI or env) ──────────────────────────────────────

MLFLOW_URL = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.platform.127.0.0.1.nip.io")
GITLAB_URL = os.getenv("GITLAB_URL", "http://gitlab.platform.127.0.0.1.nip.io")
GITLAB_PAT = os.getenv("GITLAB_PAT", "")
GITLAB_PROJECT = os.getenv("GITLAB_PROJECT", "root/platform-monorepo")
REFRESH_SECONDS = 60

# Known agents (source of truth: agents/ dir)
AGENTS = ["mlops", "developer", "platform-admin", "data-engineer", "project-coordinator", "qa-eval"]

# ── Cache ────────────────────────────────────────────────────────────────────

_cache: dict = {"evals": [], "pipelines": [], "readiness": [], "ts": 0, "errors": []}


# ── MLflow ───────────────────────────────────────────────────────────────────

async def fetch_mlflow_runs(client: httpx.AsyncClient) -> list[dict]:
    rows = []
    resp = await client.get(f"{MLFLOW_URL}/api/2.0/mlflow/experiments/search", params={"max_results": 200})
    resp.raise_for_status()
    experiments = resp.json().get("experiments", [])
    bench_exps = [e for e in experiments if "benchmark" in e.get("name", "").lower() or e.get("name", "").startswith("benchmark/")]

    for exp in bench_exps:
        exp_id = exp["experiment_id"]
        exp_name = exp["name"]
        resp = await client.post(
            f"{MLFLOW_URL}/api/2.0/mlflow/runs/search",
            json={"experiment_ids": [exp_id], "max_results": 50, "order_by": ["start_time DESC"]},
        )
        resp.raise_for_status()
        for run in resp.json().get("runs", []):
            data = run.get("data", {})
            metrics = {m["key"]: m["value"] for m in data.get("metrics", [])}
            params = {p["key"]: p["value"] for p in data.get("params", [])}
            tags = {t["key"]: t["value"] for t in data.get("tags", [])}
            info = run.get("info", {})
            start_ms = info.get("start_time", 0)
            rows.append({
                "agent": tags.get("agent", params.get("agent", "")),
                "task": tags.get("task", params.get("task", exp_name.split("/")[-1] if "/" in exp_name else "")),
                "dataset": tags.get("dataset", params.get("dataset", exp_name)),
                "method": tags.get("method", params.get("method", params.get("mode", ""))),
                "model": tags.get("model", params.get("model", "")),
                "pass_rate": metrics.get("pass_rate", metrics.get("pass_rate_pct")),
                "avg_score": metrics.get("avg_score"),
                "latency_ms": metrics.get("latency_p95", metrics.get("avg_latency_ms", metrics.get("latency_ms"))),
                "cost": metrics.get("cost", metrics.get("total_cost", metrics.get("cost_usd"))),
                "cases": metrics.get("total_cases", metrics.get("cases_evaluated")),
                "version": tags.get("version_hash", "")[:8],
                "status": info.get("status", ""),
                "time": datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if start_ms else "",
                "run_id": info.get("run_id", "")[:8],
            })
    rows.sort(key=lambda r: r["time"], reverse=True)
    return rows


# ── GitLab CI ────────────────────────────────────────────────────────────────

async def fetch_gitlab_pipelines(client: httpx.AsyncClient) -> list[dict]:
    if not GITLAB_PAT:
        return []
    headers = {"PRIVATE-TOKEN": GITLAB_PAT}
    project_encoded = GITLAB_PROJECT.replace("/", "%2F")

    # Recent pipelines
    resp = await client.get(
        f"{GITLAB_URL}/api/v4/projects/{project_encoded}/pipelines",
        headers=headers,
        params={"per_page": 15, "order_by": "updated_at", "sort": "desc"},
    )
    resp.raise_for_status()
    pipelines = resp.json()

    rows = []
    for p in pipelines:
        pid = p["id"]
        # Get jobs for this pipeline
        resp = await client.get(
            f"{GITLAB_URL}/api/v4/projects/{project_encoded}/pipelines/{pid}/jobs",
            headers=headers,
            params={"per_page": 50},
        )
        jobs = resp.json() if resp.status_code == 200 else []

        # Group jobs by stage
        stages: dict[str, list] = {}
        for j in jobs:
            stage = j.get("stage", "unknown")
            stages.setdefault(stage, []).append({
                "name": j["name"],
                "status": j["status"],
            })

        # Compute per-stage summary
        stage_summary = {}
        for stage, stage_jobs in stages.items():
            statuses = [j["status"] for j in stage_jobs]
            if "failed" in statuses:
                stage_summary[stage] = "failed"
            elif "running" in statuses:
                stage_summary[stage] = "running"
            elif all(s == "success" for s in statuses):
                stage_summary[stage] = "success"
            elif all(s in ("skipped", "manual", "created") for s in statuses):
                stage_summary[stage] = "skipped"
            else:
                stage_summary[stage] = "pending"

        created = p.get("created_at", "")
        if created:
            try:
                created = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass

        rows.append({
            "id": pid,
            "ref": p.get("ref", ""),
            "status": p.get("status", ""),
            "source": p.get("source", ""),
            "stages": stage_summary,
            "time": created,
            "web_url": p.get("web_url", ""),
        })
    return rows


# ── Agent Readiness ──────────────────────────────────────────────────────────

async def compute_readiness(evals: list[dict], pipelines: list[dict], client: httpx.AsyncClient) -> list[dict]:
    """Per-agent checklist: dataset, eval run, baseline, pipeline, promotion stage."""
    readiness = []

    # Check which datasets exist on disk
    import pathlib
    bench_dir = pathlib.Path(__file__).parent.parent / "data" / "benchmarks"

    for agent in AGENTS:
        r: dict = {"agent": agent, "dataset": False, "eval_run": False, "baseline": False, "pipeline_pass": False, "promoted": False, "details": {}}

        # 1. Dataset exists?
        agent_prefix = agent.replace("-", "")  # platform-admin → platformadmin
        datasets = list(bench_dir.glob(f"{agent}*.json*")) + list(bench_dir.glob(f"{agent_prefix}*.json*"))
        r["dataset"] = len(datasets) > 0
        r["details"]["datasets"] = len(datasets)

        # 2. Eval run exists in MLflow?
        agent_evals = [e for e in evals if e["agent"] == agent or agent in e.get("dataset", "")]
        r["eval_run"] = len(agent_evals) > 0
        if agent_evals:
            latest = agent_evals[0]
            r["details"]["latest_pass_rate"] = latest.get("pass_rate")
            r["details"]["latest_time"] = latest.get("time")

        # 3. Baseline set?
        try:
            resp = await client.post(
                f"{MLFLOW_URL}/api/2.0/mlflow/runs/search",
                json={
                    "experiment_ids": [],
                    "filter": f"tags.agent = '{agent}' AND tags.baseline = 'true'",
                    "max_results": 1,
                },
            )
            if resp.status_code == 200:
                baseline_runs = resp.json().get("runs", [])
                r["baseline"] = len(baseline_runs) > 0
        except Exception:
            pass

        # 4. Recent pipeline passed eval-candidate?
        for p in pipelines:
            eval_stage = p["stages"].get("eval-candidate")
            if eval_stage == "success":
                r["pipeline_pass"] = True
                break

        # 5. Prompt promoted to production?
        try:
            resp = await client.get(
                f"{MLFLOW_URL}/api/2.0/mlflow/registered-models/get",
                params={"name": f"{agent}.SYSTEM"},
            )
            if resp.status_code == 200:
                model = resp.json().get("registered_model", {})
                aliases = model.get("aliases", [])
                r["promoted"] = any(a.get("alias") == "production" for a in aliases)
        except Exception:
            pass

        readiness.append(r)
    return readiness


# ── Refresh ──────────────────────────────────────────────────────────────────

async def refresh_all():
    now = time.time()
    if now - _cache["ts"] < REFRESH_SECONDS:
        return
    errors = []
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            _cache["evals"] = await fetch_mlflow_runs(client)
        except Exception as e:
            errors.append(f"MLflow: {e}")

        try:
            _cache["pipelines"] = await fetch_gitlab_pipelines(client)
        except Exception as e:
            errors.append(f"GitLab: {e}")

        try:
            _cache["readiness"] = await compute_readiness(_cache["evals"], _cache["pipelines"], client)
        except Exception as e:
            errors.append(f"Readiness: {e}")

    _cache["errors"] = errors
    _cache["ts"] = now


# ── Formatters ───────────────────────────────────────────────────────────────

def fmt(val, kind: str = "") -> str:
    if val is None:
        return '<span class="dim">—</span>'
    if kind == "rate":
        v = float(val)
        if v <= 1:
            v *= 100
        c = "green" if v >= 80 else "yellow" if v >= 60 else "red"
        return f'<span class="{c} bold">{v:.1f}%</span>'
    if kind == "latency":
        v = float(val)
        c = "green" if v < 5000 else "yellow" if v < 15000 else "red"
        return f'<span class="{c}">{v:.0f}ms</span>'
    if kind == "cost":
        return f"${float(val):.4f}"
    if kind == "score":
        v = float(val)
        c = "green" if v >= 4 else "yellow" if v >= 3 else "red"
        return f'<span class="{c}">{v:.2f}</span>'
    return str(val)


def check(ok: bool) -> str:
    return '<span class="green">✓</span>' if ok else '<span class="red">✗</span>'


def pipeline_status_icon(status: str) -> str:
    icons = {"success": '<span class="green">●</span>', "failed": '<span class="red">●</span>', "running": '<span class="yellow">◌</span>', "skipped": '<span class="dim">○</span>', "pending": '<span class="dim">◌</span>', "manual": '<span class="blue">◆</span>', "created": '<span class="dim">○</span>', "canceled": '<span class="dim">○</span>'}
    return icons.get(status, f'<span class="dim">{status}</span>')


STAGE_ORDER = ["lint", "validate", "eval-candidate", "deploy-staging", "integration-test", "deploy-prod", "post-deploy-eval", "feedback"]


# ── HTML ─────────────────────────────────────────────────────────────────────

def render_html() -> str:
    evals = _cache["evals"]
    pipelines = _cache["pipelines"]
    readiness = _cache["readiness"]
    errors = _cache["errors"]
    now = datetime.now().strftime("%H:%M:%S")

    error_html = ""
    for e in errors:
        error_html += f'<div class="error-banner">{e}</div>'

    # ── Section 1: Agent Readiness ───────────────────────────────────────────
    readiness_rows = ""
    for r in readiness:
        pr = r["details"].get("latest_pass_rate")
        pr_fmt = fmt(pr, "rate") if pr is not None else '<span class="dim">—</span>'
        score = sum([r["dataset"], r["eval_run"], r["baseline"], r["pipeline_pass"], r["promoted"]])
        score_c = "green" if score == 5 else "yellow" if score >= 3 else "red"
        readiness_rows += f"""<tr>
            <td class="bold">{r['agent']}</td>
            <td style="text-align:center">{check(r['dataset'])}</td>
            <td style="text-align:center">{check(r['eval_run'])}</td>
            <td style="text-align:center">{check(r['baseline'])}</td>
            <td style="text-align:center">{check(r['pipeline_pass'])}</td>
            <td style="text-align:center">{check(r['promoted'])}</td>
            <td>{pr_fmt}</td>
            <td><span class="{score_c} bold">{score}/5</span></td>
        </tr>"""

    # ── Section 2: Pipelines ─────────────────────────────────────────────────
    pipeline_rows = ""
    for p in pipelines:
        stage_cells = ""
        for s in STAGE_ORDER:
            st = p["stages"].get(s)
            stage_cells += f'<td style="text-align:center">{pipeline_status_icon(st) if st else '<span class="dim">·</span>'}</td>'
        pipeline_rows += f"""<tr>
            <td class="mono dim" style="font-size:11px">{p['id']}</td>
            <td>{p['ref']}</td>
            <td>{pipeline_status_icon(p['status'])} {p['status']}</td>
            <td class="dim" style="font-size:11px">{p['source']}</td>
            {stage_cells}
            <td class="dim" style="font-size:11px">{p['time']}</td>
        </tr>"""
    if not pipelines:
        cols = 4 + len(STAGE_ORDER) + 1
        msg = "No GITLAB_PAT set" if not GITLAB_PAT else "No pipelines found"
        pipeline_rows = f'<tr><td colspan="{cols}" class="empty">{msg}</td></tr>'

    # ── Section 3: Eval Runs ─────────────────────────────────────────────────
    eval_rows = ""
    for r in evals:
        sc = "green" if r["status"] == "FINISHED" else "yellow" if r["status"] == "RUNNING" else "red"
        eval_rows += f"""<tr>
            <td>{r['agent'] or '—'}</td>
            <td>{r['task']}</td>
            <td class="dim" style="font-size:11px">{r['dataset']}</td>
            <td>{r['method'] or '—'}</td>
            <td class="blue">{r['model'] or '—'}</td>
            <td>{fmt(r['pass_rate'], 'rate')}</td>
            <td>{fmt(r['avg_score'], 'score')}</td>
            <td>{fmt(r['latency_ms'], 'latency')}</td>
            <td>{fmt(r['cost'], 'cost')}</td>
            <td style="text-align:center">{int(r['cases']) if r['cases'] else '—'}</td>
            <td class="mono dim" style="font-size:10px">{r['version'] or '—'}</td>
            <td><span class="{sc}">●</span></td>
            <td class="dim" style="font-size:11px">{r['time']}</td>
        </tr>"""
    if not evals and not errors:
        eval_rows = '<tr><td colspan="13" class="empty">No benchmark runs found. Run: task mlops:eval</td></tr>'

    stage_headers = "".join(f"<th>{s.replace('-', '<br/>')}</th>" for s in STAGE_ORDER)

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="{REFRESH_SECONDS}">
    <title>eval-board</title>
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ background:#0f172a; color:#e2e8f0; font-family:'SF Mono','Fira Code',monospace; font-size:13px; }}
        .header {{ display:flex; align-items:center; gap:12px; padding:10px 20px; background:#1e1e2e; border-bottom:1px solid #334155; }}
        .header h1 {{ font-size:14px; color:#22c55e; font-weight:700; }}
        .header .meta {{ margin-left:auto; color:#475569; font-size:11px; }}
        .section {{ padding:12px 20px 4px; }}
        .section h2 {{ font-size:12px; color:#94a3b8; font-weight:600; text-transform:uppercase; letter-spacing:1px; margin-bottom:8px; }}
        table {{ width:100%; border-collapse:collapse; margin-bottom:16px; }}
        th {{ text-align:left; padding:6px 10px; background:#1e1e2e; color:#64748b; font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; border-bottom:2px solid #334155; position:sticky; top:0; white-space:nowrap; }}
        td {{ padding:5px 10px; border-bottom:1px solid #1e293b; white-space:nowrap; }}
        tr:hover {{ background:#1e293b; }}
        .wrap {{ overflow-x:auto; height:calc(100vh - 45px); }}
        .green {{ color:#22c55e; }} .yellow {{ color:#eab308; }} .red {{ color:#ef4444; }} .blue {{ color:#a5b4fc; }} .dim {{ color:#475569; }}
        .bold {{ font-weight:600; }} .mono {{ font-family:monospace; }}
        .error-banner {{ background:#450a0a; border:1px solid #ef4444; padding:6px 16px; margin:8px 20px; border-radius:4px; color:#fca5a5; font-size:12px; }}
        .empty {{ text-align:center; color:#475569; padding:30px; }}
        .counts {{ color:#64748b; font-size:11px; margin-left:8px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>eval-board</h1>
        <span class="counts">{len(evals)} evals &middot; {len(pipelines)} pipelines &middot; {len(readiness)} agents</span>
        <span class="meta">refreshes {REFRESH_SECONDS}s &middot; {now}</span>
    </div>
    {error_html}
    <div class="wrap">

    <div class="section">
        <h2>Agent Readiness</h2>
        <table>
            <thead><tr>
                <th>Agent</th><th>Dataset</th><th>Eval Run</th><th>Baseline</th><th>CI Pass</th><th>Promoted</th><th>Pass Rate</th><th>Score</th>
            </tr></thead>
            <tbody>{readiness_rows}</tbody>
        </table>
    </div>

    <div class="section">
        <h2>CI/CD Pipelines</h2>
        <table>
            <thead><tr>
                <th>ID</th><th>Ref</th><th>Status</th><th>Source</th>{stage_headers}<th>Time</th>
            </tr></thead>
            <tbody>{pipeline_rows}</tbody>
        </table>
    </div>

    <div class="section">
        <h2>Eval Runs</h2>
        <table>
            <thead><tr>
                <th>Agent</th><th>Task</th><th>Dataset</th><th>Method</th><th>Model</th><th>Pass Rate</th><th>Score</th><th>Latency</th><th>Cost</th><th>Cases</th><th>Version</th><th>St</th><th>Time</th>
            </tr></thead>
            <tbody>{eval_rows}</tbody>
        </table>
    </div>

    </div>
</body>
</html>"""


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    await refresh_all()
    return render_html()


@app.get("/health")
async def health():
    return {"status": "ok", "evals": len(_cache["evals"]), "pipelines": len(_cache["pipelines"]), "agents": len(_cache["readiness"])}


@app.get("/api/evals")
async def api_evals():
    await refresh_all()
    return {"runs": _cache["evals"], "count": len(_cache["evals"])}


@app.get("/api/pipelines")
async def api_pipelines():
    await refresh_all()
    return {"pipelines": _cache["pipelines"], "count": len(_cache["pipelines"])}


@app.get("/api/readiness")
async def api_readiness():
    await refresh_all()
    return {"agents": _cache["readiness"]}


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AgentOps eval board")
    parser.add_argument("--port", type=int, default=4021)
    parser.add_argument("--mlflow", default=None)
    parser.add_argument("--gitlab", default=None)
    parser.add_argument("--gitlab-pat", default=None)
    parser.add_argument("--project", default=None)
    parser.add_argument("--refresh", type=int, default=60)
    args = parser.parse_args()

    if args.mlflow:
        MLFLOW_URL = args.mlflow
    if args.gitlab:
        GITLAB_URL = args.gitlab
    if args.gitlab_pat:
        GITLAB_PAT = args.gitlab_pat
    if args.project:
        GITLAB_PROJECT = args.project
    REFRESH_SECONDS = args.refresh

    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")
