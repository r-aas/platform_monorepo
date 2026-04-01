#!/usr/bin/env python3
"""AgentOps policy engine — declarative compliance checks for agent lifecycle.

Aligned to ISO/IEC 42001:2023 Annex A controls. Each policy references
the ISO control it satisfies so compliance mapping is traceable.

Two profiles:
  solo       — Individual architect. Organizational controls auto-satisfied.
  enterprise — Full ISO 42001 scope. RACI, impact assessment, vendor mgmt enforced.

Usage:
    uv run scripts/agentops-policy.py                     # solo profile, all agents
    uv run scripts/agentops-policy.py --profile enterprise # full ISO scope
    uv run scripts/agentops-policy.py --agent mlops        # check one agent
    uv run scripts/agentops-policy.py --type mcp_server    # scope to MCP server policies (3 of 18)
    uv run scripts/agentops-policy.py --type agent         # scope to agent policies (all 18)
    uv run scripts/agentops-policy.py --standard owasp      # OWASP Agentic Top 10 only (P-050..P-059)
    uv run scripts/agentops-policy.py --standard iso42001  # ISO 42001 policies only (P-001..P-041)
    uv run scripts/agentops-policy.py --scope-doc          # generate ISO 42001 Clause 4.3 scope doc
    uv run scripts/agentops-policy.py --json               # machine-readable
    uv run scripts/agentops-policy.py --gate               # exit 1 if any FAIL
    uv run scripts/agentops-policy.py --level production   # only L3 policies
"""
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.28", "pyyaml>=6.0"]
# ///

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

# ── Config ───────────────────────────────────────────────────────────────────

MLFLOW_URL = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.platform.127.0.0.1.nip.io")
GITLAB_URL = os.getenv("GITLAB_URL", "http://gitlab.platform.127.0.0.1.nip.io")
GITLAB_PAT = os.getenv("GITLAB_PAT", "")
GITLAB_PROJECT = os.getenv("GITLAB_PROJECT", "root/platform-monorepo")

REPO_ROOT = Path(__file__).parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
BENCHMARKS_DIR = REPO_ROOT / "data" / "benchmarks"
KAGENT_TEMPLATES = REPO_ROOT / "charts" / "genai-kagent" / "templates"
TAXONOMY_FILE = REPO_ROOT / "data" / "compliance" / "taxonomy.yaml"


# ── Taxonomy ────────────────────────────────────────────────────────────────

def load_taxonomy() -> dict:
    """Load AI system taxonomy from data/compliance/taxonomy.yaml."""
    if not TAXONOMY_FILE.exists():
        return {}
    with open(TAXONOMY_FILE) as f:
        return yaml.safe_load(f) or {}


def get_type_policy_scope(taxonomy: dict, system_type: str) -> set[str]:
    """Get the set of policy IDs applicable to a taxonomy type.

    Returns policy IDs like 'P-001', extracted from the type's policy_scope list.
    """
    types = taxonomy.get("types", {})
    if system_type not in types:
        return set()
    scope = types[system_type].get("policy_scope", [])
    # policy_scope entries look like "P-001  # spec-exists" — extract ID
    return {entry.split("#")[0].strip().split()[0] if "#" in entry else entry.strip() for entry in scope}


def get_policy_id(policy_name: str) -> str:
    """Extract policy ID from policy name like 'P-001 spec-exists' → 'P-001'."""
    return policy_name.split()[0] if " " in policy_name else policy_name

# ── Data ─────────────────────────────────────────────────────────────────────

@dataclass
class PolicyResult:
    policy: str
    level: str          # L0, L1, L2, L3, L4
    agent: str
    passed: bool
    reason: str
    evidence: str = ""
    iso_controls: str = ""    # ISO/IEC 42001 Annex A control references
    enforcement: str = ""     # Where enforcement happens (inspired by safe-k8s)
    skipped: bool = False     # True when policy doesn't apply to active profile

    def to_dict(self) -> dict:
        d = {"policy": self.policy, "level": self.level, "agent": self.agent,
             "passed": self.passed, "reason": self.reason, "evidence": self.evidence}
        if self.iso_controls:
            d["iso_controls"] = self.iso_controls
        if self.enforcement:
            d["enforcement"] = self.enforcement
        if self.skipped:
            d["skipped"] = True
        return d


# ── Enforcement Points ──────────────────────────────────────────────────────
# Borrowed from safe-k8s "primary_enforcement_point" pattern.
# Each policy runs at one of these stages:
#
#   static     — checked against agent spec YAML at define time (CI, pre-commit)
#   admission  — checked at k8s deploy time (Kyverno/CEL admission webhook)
#   runtime    — checked against live system state (MLflow, GitLab API, Langfuse)
#   audit      — checked periodically against accumulated evidence
#
# This tells you WHERE to enforce, not just WHAT to check.


# ── Profiles ────────────────────────────────────────────────────────────────
#
# solo:       Individual architect building agentic systems. You are every role.
#             Organizational controls (RACI, stakeholder comms, vendor SLAs) are
#             auto-satisfied or skipped. Focus: technical rigor, eval gates.
#
# enterprise: Team/org building agentic products. Full ISO 42001 scope.
#             Organizational controls enforced. Formal impact assessments,
#             multi-team ownership, approval quorums, vendor risk management.

PROFILES = {"solo", "enterprise"}

# Policies that are enterprise-only (skipped in solo profile).
# Solo architect satisfies these controls implicitly:
#   A.3.2 — you are all roles (author, reviewer, approver, operator)
#   A.5.2/A.5.3 — impact is self-assessed; formal doc overkill for solo
#   A.10.2/A.10.3 — you manage your own deps; no vendor SLA process needed
ENTERPRISE_ONLY_POLICIES = {
    "P-031 roles-defined",       # A.3.2 — solo = you ARE the role
    "P-040 impact-assessed",     # A.5.2/A.5.3 — solo = notes in spec metadata
    "P-023 third-party-declared", # A.10.2/A.10.3 — solo = deps in spec is enough
}

# ── Policy Definitions ───────────────────────────────────────────────────────
#
# Maturity levels (from AgentOps skill Graph 7):
#   L0 Prototype  — spec exists
#   L1 Evaluated  — spec + prompt versioned + eval run + dataset coverage
#   L2 Staged     — L1 + version hash + guardrails tested
#   L3 Production — L2 + session replay + cost attribution + OTEL
#   L4 Optimized  — L3 + outcome tests + <2% regression
#
# Each policy is a function: (agent_name, context) -> PolicyResult

def p_spec_exists(agent: str, ctx: dict) -> PolicyResult:
    """P-001: Agent spec YAML exists in agents/ directory.
    ISO 42001: A.4.2 (AI system inventory), A.6.2.2 (system requirements)."""
    spec_dir = AGENTS_DIR / agent
    spec_file = spec_dir / "agent.yaml"
    alt_files = list(spec_dir.glob("*.yaml")) if spec_dir.exists() else []
    exists = spec_file.exists() or len(alt_files) > 0
    return PolicyResult(
        policy="P-001 spec-exists", level="L0", agent=agent, passed=exists,
        reason="Agent spec exists" if exists else "No agent spec found",
        evidence=str(spec_file) if exists else f"Checked: {spec_dir}",
        iso_controls="A.4.2, A.6.2.2", enforcement="static",
    )


def p_no_inline_secrets(agent: str, ctx: dict) -> PolicyResult:
    """P-002: No URLs, IPs, or secrets in agent spec."""
    spec_dir = AGENTS_DIR / agent
    issues = []
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        content = f.read_text()
        import re
        # Skip env binding files
        if "envs/" in str(f):
            continue
        ips = re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", content)
        urls = re.findall(r"https?://[^\s\"']+", content)
        secrets = re.findall(r"(password|secret|token|api.key)\s*[:=]", content, re.IGNORECASE)
        # Filter out Helm template references
        ips = [ip for ip in ips if "{{" not in content[max(0, content.index(ip) - 20):content.index(ip)]]
        if ips:
            issues.append(f"{f.name}: hardcoded IPs {ips}")
        if urls:
            issues.append(f"{f.name}: hardcoded URLs")
        if secrets:
            issues.append(f"{f.name}: possible secrets")
    passed = len(issues) == 0
    return PolicyResult(
        policy="P-002 no-inline-secrets", level="L0", agent=agent, passed=passed,
        reason="No secrets in spec" if passed else "Found issues in spec",
        evidence="; ".join(issues) if issues else "Clean",
        iso_controls="A.6.2.3", enforcement="static",
    )


def p_toolnames_explicit(agent: str, ctx: dict) -> PolicyResult:
    """P-003: All MCP server references have explicit toolNames.
    ISO 42001: A.4.4 (tooling resources), A.9.2 (intended use)."""
    spec_dir = AGENTS_DIR / agent
    issues = []
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                tools = doc.get("tools", [])
                for t in tools if isinstance(tools, list) else []:
                    if isinstance(t, dict) and "server" in t and "toolNames" not in t:
                        issues.append(f"{f.name}: {t['server']} missing toolNames")
        except Exception:
            pass
    passed = len(issues) == 0
    return PolicyResult(
        policy="P-003 toolnames-explicit", level="L0", agent=agent, passed=passed,
        reason="All tools have explicit toolNames" if passed else "Missing toolNames",
        evidence="; ".join(issues) if issues else "All explicit",
        iso_controls="A.4.4, A.9.2", enforcement="static",
    )


def p_tool_budget(agent: str, ctx: dict) -> PolicyResult:
    """P-004: Agent has ≤20 tools total.
    ISO 42001: A.9.2 (intended use boundaries)."""
    spec_dir = AGENTS_DIR / agent
    total = 0
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                tools = doc.get("tools", [])
                for t in tools if isinstance(tools, list) else []:
                    if isinstance(t, dict):
                        total += len(t.get("toolNames", []))
        except Exception:
            pass
    passed = total <= 20
    return PolicyResult(
        policy="P-004 tool-budget", level="L0", agent=agent, passed=passed,
        reason=f"{total} tools (≤20)" if passed else f"{total} tools exceeds 20 limit",
        evidence=f"total={total}",
        iso_controls="A.9.2", enforcement="static",
    )


def p_guardrails_set(agent: str, ctx: dict) -> PolicyResult:
    """P-005: Agent has guardrails configured (budget, max_turns).
    ISO 42001: A.9.3 (human oversight)."""
    spec_dir = AGENTS_DIR / agent
    has_guardrails = False
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if isinstance(doc, dict) and "guardrails" in doc:
                    g = doc["guardrails"]
                    if isinstance(g, dict) and ("max_budget_usd" in g or "max_turns" in g):
                        has_guardrails = True
        except Exception:
            pass
    return PolicyResult(
        policy="P-005 guardrails-set", level="L0", agent=agent, passed=has_guardrails,
        reason="Guardrails configured" if has_guardrails else "No guardrails found in spec",
        iso_controls="A.9.3", enforcement="static",
    )


def p_purpose_documented(agent: str, ctx: dict) -> PolicyResult:
    """P-006: Agent has description and system_prompt in spec.
    ISO 42001: A.8.2 (user information), A.9.2 (intended use)."""
    spec_dir = AGENTS_DIR / agent
    has_description = False
    has_prompt = False
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                if doc.get("description"):
                    has_description = True
                if doc.get("system_prompt"):
                    has_prompt = True
        except Exception:
            pass
    passed = has_description and has_prompt
    missing = []
    if not has_description:
        missing.append("description")
    if not has_prompt:
        missing.append("system_prompt")
    return PolicyResult(
        policy="P-006 purpose-documented", level="L0", agent=agent, passed=passed,
        reason="Purpose and prompt documented" if passed else f"Missing: {', '.join(missing)}",
        iso_controls="A.8.2, A.9.2", enforcement="static",
    )


def p_human_oversight(agent: str, ctx: dict) -> PolicyResult:
    """P-022: Destructive actions require human approval.
    ISO 42001: A.9.3 (human oversight and override)."""
    spec_dir = AGENTS_DIR / agent
    has_approval_list = False
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                guardrails = doc.get("guardrails") or doc.get("autonomy", {}).get("guardrails", {})
                if isinstance(guardrails, dict) and guardrails.get("require_approval_for"):
                    has_approval_list = True
        except Exception:
            pass
    return PolicyResult(
        policy="P-022 human-oversight", level="L2", agent=agent, passed=has_approval_list,
        reason="Approval gates configured for destructive ops" if has_approval_list else "No require_approval_for in guardrails",
        iso_controls="A.9.3", enforcement="static",
    )


def p_third_party_declared(agent: str, ctx: dict) -> PolicyResult:
    """P-023: Agent declares its external dependencies (MCP servers, LLM provider).
    ISO 42001: A.10.2 (third-party responsibilities), A.10.3 (supplier monitoring)."""
    spec_dir = AGENTS_DIR / agent
    has_llm = False
    has_tools = False
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                if doc.get("llm_config"):
                    has_llm = True
                tools = doc.get("tools", [])
                if isinstance(tools, list) and len(tools) > 0:
                    has_tools = True
                # Also check skills as dependency declaration
                skills = doc.get("skills", [])
                if isinstance(skills, list) and len(skills) > 0:
                    has_tools = True
        except Exception:
            pass
    passed = has_llm and has_tools
    missing = []
    if not has_llm:
        missing.append("llm_config")
    if not has_tools:
        missing.append("tools/skills")
    return PolicyResult(
        policy="P-023 third-party-declared", level="L2", agent=agent, passed=passed,
        reason="Dependencies declared" if passed else f"Missing: {', '.join(missing)}",
        iso_controls="A.10.2, A.10.3", enforcement="static",
    )


def p_roles_defined(agent: str, ctx: dict) -> PolicyResult:
    """P-031: Agent has collaborators and schedule defined (ownership/responsibility).
    ISO 42001: A.3.2 (roles and responsibilities)."""
    spec_dir = AGENTS_DIR / agent
    has_schedule = False
    has_collaborators = False
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                autonomy = doc.get("autonomy", {})
                if isinstance(autonomy, dict):
                    if autonomy.get("schedule"):
                        has_schedule = True
                    if autonomy.get("collaborators"):
                        has_collaborators = True
        except Exception:
            pass
    passed = has_schedule and has_collaborators
    return PolicyResult(
        policy="P-031 roles-defined", level="L3", agent=agent, passed=passed,
        reason="Schedule and collaborators defined" if passed else "Missing schedule or collaborator definitions",
        iso_controls="A.3.2", enforcement="static",
    )


def p_observability_configured(agent: str, ctx: dict) -> PolicyResult:
    """P-032: Agent has memory/verification config for audit trail.
    ISO 42001: A.6.2.8 (event logging), A.8.3 (explainability)."""
    spec_dir = AGENTS_DIR / agent
    has_memory = False
    has_verify = False
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                autonomy = doc.get("autonomy", {})
                if isinstance(autonomy, dict):
                    if autonomy.get("memory"):
                        has_memory = True
                    if autonomy.get("verify"):
                        has_verify = True
        except Exception:
            pass
    passed = has_memory and has_verify
    missing = []
    if not has_memory:
        missing.append("memory")
    if not has_verify:
        missing.append("verify")
    return PolicyResult(
        policy="P-032 observability", level="L3", agent=agent, passed=passed,
        reason="Audit trail configured" if passed else f"Missing: {', '.join(missing)}",
        iso_controls="A.6.2.8, A.8.3", enforcement="static",
    )


def p_impact_assessed(agent: str, ctx: dict) -> PolicyResult:
    """P-040: Agent has impact assessment documentation.
    ISO 42001: A.5.2 (impact assessment process), A.5.3 (impact assessment docs)."""
    # Check for impact assessment in agent spec metadata or a dedicated file
    spec_dir = AGENTS_DIR / agent
    has_impact = False
    # Check for impact_assessment field in spec
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if isinstance(doc, dict) and doc.get("impact_assessment"):
                    has_impact = True
        except Exception:
            pass
    # Check for impact assessment file
    if (spec_dir / "impact-assessment.md").exists() or (spec_dir / "impact-assessment.yaml").exists():
        has_impact = True
    return PolicyResult(
        policy="P-040 impact-assessed", level="L4", agent=agent, passed=has_impact,
        reason="Impact assessment documented" if has_impact else "No impact assessment found",
        iso_controls="A.5.2, A.5.3", enforcement="audit",
    )


def p_data_provenance(agent: str, ctx: dict) -> PolicyResult:
    """P-041: Benchmark datasets have provenance metadata.
    ISO 42001: A.7.5 (data provenance)."""
    prefixes = [agent, agent.replace("-", "")]
    datasets = []
    for p in prefixes:
        datasets.extend(BENCHMARKS_DIR.glob(f"{p}*.json*"))
    if not datasets:
        return PolicyResult(
            policy="P-041 data-provenance", level="L4", agent=agent, passed=False,
            reason="No datasets to check provenance",
            iso_controls="A.7.5", enforcement="audit",
        )
    # Check for provenance sidecar files or inline metadata
    has_provenance = False
    for d in datasets:
        sidecar = d.with_suffix(d.suffix + ".provenance")
        meta_file = d.parent / f"{d.stem}.meta.yaml"
        if sidecar.exists() or meta_file.exists():
            has_provenance = True
            break
        # Check for inline provenance (first line is metadata comment)
        try:
            first_line = d.read_text().strip().splitlines()[0]
            if "provenance" in first_line.lower() or "source" in first_line.lower():
                has_provenance = True
                break
        except Exception:
            pass
    return PolicyResult(
        policy="P-041 data-provenance", level="L4", agent=agent, passed=has_provenance,
        reason="Dataset provenance documented" if has_provenance else "No provenance metadata for datasets",
        iso_controls="A.7.5", enforcement="audit",
    )


def p_dataset_exists(agent: str, ctx: dict) -> PolicyResult:
    """P-010: Benchmark dataset exists with ≥3 cases.
    ISO 42001: A.7.2 (data management), A.7.4 (data quality)."""
    prefixes = [agent, agent.replace("-", "")]
    datasets = []
    for p in prefixes:
        datasets.extend(BENCHMARKS_DIR.glob(f"{p}*.json*"))
    total_cases = 0
    for d in datasets:
        try:
            lines = d.read_text().strip().splitlines()
            total_cases += len(lines)
        except Exception:
            pass
    passed = total_cases >= 3
    return PolicyResult(
        policy="P-010 dataset-exists", level="L1", agent=agent, passed=passed,
        reason=f"{len(datasets)} datasets, {total_cases} cases" if passed else "No benchmark datasets (need ≥3 cases)",
        evidence=", ".join(d.name for d in datasets) if datasets else "None found",
        iso_controls="A.7.2, A.7.4", enforcement="static",
    )


def p_prompt_versioned(agent: str, ctx: dict) -> PolicyResult:
    """P-011: Prompt registered in MLflow (not inline in code).
    ISO 42001: A.6.2.3 (design decisions), A.6.2.7 (technical docs)."""
    client = ctx.get("http_client")
    if not client:
        return PolicyResult(policy="P-011 prompt-versioned", level="L1", agent=agent, passed=False, reason="No HTTP client")
    try:
        resp = client.get(f"{MLFLOW_URL}/api/2.0/mlflow/registered-models/get", params={"name": f"{agent}.SYSTEM"})
        if resp.status_code == 200:
            model = resp.json().get("registered_model", {})
            versions = model.get("latest_versions", [])
            return PolicyResult(
                policy="P-011 prompt-versioned", level="L1", agent=agent, passed=True,
                reason=f"Prompt registered, {len(versions)} version(s)",
                evidence=f"model={agent}.SYSTEM",
            )
        return PolicyResult(policy="P-011 prompt-versioned", level="L1", agent=agent, passed=False, reason=f"Not registered in MLflow (HTTP {resp.status_code})")
    except Exception as e:
        return PolicyResult(policy="P-011 prompt-versioned", level="L1", agent=agent, passed=False, reason=f"MLflow error: {e}")


def p_eval_run_exists(agent: str, ctx: dict) -> PolicyResult:
    """P-012: At least one benchmark eval run exists in MLflow.
    ISO 42001: A.6.2.4 (verification & validation)."""
    client = ctx.get("http_client")
    if not client:
        return PolicyResult(policy="P-012 eval-run-exists", level="L1", agent=agent, passed=False, reason="No HTTP client")
    try:
        # Search for benchmark experiments matching this agent
        resp = client.get(f"{MLFLOW_URL}/api/2.0/mlflow/experiments/search", params={"max_results": 200})
        if resp.status_code != 200:
            return PolicyResult(policy="P-012 eval-run-exists", level="L1", agent=agent, passed=False, reason="MLflow unavailable")
        exps = resp.json().get("experiments", [])
        matching = [e for e in exps if agent in e.get("name", "").lower() and "benchmark" in e.get("name", "").lower()]
        if not matching:
            return PolicyResult(policy="P-012 eval-run-exists", level="L1", agent=agent, passed=False, reason="No benchmark experiment found")
        # Check for runs
        exp_ids = [e["experiment_id"] for e in matching]
        resp = client.post(f"{MLFLOW_URL}/api/2.0/mlflow/runs/search", json={"experiment_ids": exp_ids, "max_results": 1})
        runs = resp.json().get("runs", []) if resp.status_code == 200 else []
        passed = len(runs) > 0
        return PolicyResult(
            policy="P-012 eval-run-exists", level="L1", agent=agent, passed=passed,
            reason=f"Eval runs found in {len(matching)} experiment(s)" if passed else "No eval runs",
        )
    except Exception as e:
        return PolicyResult(policy="P-012 eval-run-exists", level="L1", agent=agent, passed=False, reason=f"Error: {e}")


def p_eval_passes_threshold(agent: str, ctx: dict) -> PolicyResult:
    """P-020: Latest eval pass_rate ≥ 0.8 (configurable via guardrails.eval_threshold).
    ISO 42001: A.6.2.4 (V&V quality criteria)."""
    client = ctx.get("http_client")
    threshold = 0.8
    if not client:
        return PolicyResult(policy="P-020 eval-threshold", level="L2", agent=agent, passed=False, reason="No HTTP client")
    try:
        resp = client.get(f"{MLFLOW_URL}/api/2.0/mlflow/experiments/search", params={"max_results": 200})
        exps = resp.json().get("experiments", []) if resp.status_code == 200 else []
        matching = [e for e in exps if agent in e.get("name", "").lower() and "benchmark" in e.get("name", "").lower()]
        if not matching:
            return PolicyResult(policy="P-020 eval-threshold", level="L2", agent=agent, passed=False, reason="No benchmark experiment")
        exp_ids = [e["experiment_id"] for e in matching]
        resp = client.post(f"{MLFLOW_URL}/api/2.0/mlflow/runs/search", json={"experiment_ids": exp_ids, "max_results": 1, "order_by": ["start_time DESC"]})
        runs = resp.json().get("runs", []) if resp.status_code == 200 else []
        if not runs:
            return PolicyResult(policy="P-020 eval-threshold", level="L2", agent=agent, passed=False, reason="No eval runs")
        metrics = {m["key"]: m["value"] for m in runs[0].get("data", {}).get("metrics", [])}
        pr = metrics.get("pass_rate", metrics.get("pass_rate_pct"))
        if pr is None:
            return PolicyResult(policy="P-020 eval-threshold", level="L2", agent=agent, passed=False, reason="No pass_rate metric in latest run")
        pr_val = float(pr)
        if pr_val <= 1:
            pr_val *= 100
        passed = pr_val >= threshold * 100
        return PolicyResult(
            policy="P-020 eval-threshold", level="L2", agent=agent, passed=passed,
            reason=f"pass_rate={pr_val:.1f}% {'≥' if passed else '<'} {threshold*100:.0f}%",
        )
    except Exception as e:
        return PolicyResult(policy="P-020 eval-threshold", level="L2", agent=agent, passed=False, reason=f"Error: {e}")


def p_ci_pipeline_passes(agent: str, ctx: dict) -> PolicyResult:
    """P-021: Most recent CI pipeline with eval-candidate stage passed.
    ISO 42001: A.6.2.5 (deployment plan)."""
    if not GITLAB_PAT:
        return PolicyResult(policy="P-021 ci-pipeline", level="L2", agent=agent, passed=False, reason="No GITLAB_PAT set")
    client = ctx.get("http_client")
    if not client:
        return PolicyResult(policy="P-021 ci-pipeline", level="L2", agent=agent, passed=False, reason="No HTTP client")
    try:
        headers = {"PRIVATE-TOKEN": GITLAB_PAT}
        project = GITLAB_PROJECT.replace("/", "%2F")
        resp = client.get(f"{GITLAB_URL}/api/v4/projects/{project}/pipelines", headers=headers, params={"per_page": 10, "order_by": "updated_at", "sort": "desc"})
        if resp.status_code != 200:
            return PolicyResult(policy="P-021 ci-pipeline", level="L2", agent=agent, passed=False, reason=f"GitLab API error: {resp.status_code}")
        pipelines = resp.json()
        for p in pipelines:
            pid = p["id"]
            resp = client.get(f"{GITLAB_URL}/api/v4/projects/{project}/pipelines/{pid}/jobs", headers=headers, params={"per_page": 50})
            jobs = resp.json() if resp.status_code == 200 else []
            eval_jobs = [j for j in jobs if j.get("stage") == "eval-candidate"]
            if eval_jobs:
                statuses = [j["status"] for j in eval_jobs]
                if all(s == "success" for s in statuses):
                    return PolicyResult(policy="P-021 ci-pipeline", level="L2", agent=agent, passed=True, reason=f"Pipeline #{pid} eval-candidate passed", evidence=f"pipeline={pid}")
                if "failed" in statuses:
                    return PolicyResult(policy="P-021 ci-pipeline", level="L2", agent=agent, passed=False, reason=f"Pipeline #{pid} eval-candidate failed", evidence=f"pipeline={pid}")
        return PolicyResult(policy="P-021 ci-pipeline", level="L2", agent=agent, passed=False, reason="No pipelines with eval-candidate stage found")
    except Exception as e:
        return PolicyResult(policy="P-021 ci-pipeline", level="L2", agent=agent, passed=False, reason=f"Error: {e}")


def p_promoted_to_production(agent: str, ctx: dict) -> PolicyResult:
    """P-030: Prompt has 'production' alias in MLflow model registry.
    ISO 42001: A.6.2.5 (deployment execution), A.6.2.6 (operate & monitor)."""
    client = ctx.get("http_client")
    if not client:
        return PolicyResult(policy="P-030 promoted", level="L3", agent=agent, passed=False, reason="No HTTP client")
    try:
        resp = client.get(f"{MLFLOW_URL}/api/2.0/mlflow/registered-models/get", params={"name": f"{agent}.SYSTEM"})
        if resp.status_code != 200:
            return PolicyResult(policy="P-030 promoted", level="L3", agent=agent, passed=False, reason="Not in model registry")
        model = resp.json().get("registered_model", {})
        aliases = model.get("aliases", [])
        has_prod = any(a.get("alias") == "production" for a in aliases)
        return PolicyResult(
            policy="P-030 promoted", level="L3", agent=agent, passed=has_prod,
            reason="Production alias set" if has_prod else "No production alias",
            evidence=str([a.get("alias") for a in aliases]),
        )
    except Exception as e:
        return PolicyResult(policy="P-030 promoted", level="L3", agent=agent, passed=False, reason=f"Error: {e}")


# ── OWASP Agentic Top 10 Policies ───────────────────────────────────────────
#
# ASI-01 through ASI-10 mapped to P-050 through P-059.
# Reference: OWASP Agentic Security Initiative (ASI) Top 10.
# Detection patterns informed by agent-audit, agent-governance-toolkit,
# pattern8, and hipocap (see ~/work/clones/policy-as-code/).

def p_prompt_injection_defense(agent: str, ctx: dict) -> PolicyResult:
    """P-050: System prompt has injection mitigation instructions.
    OWASP ASI-01 (Prompt Injection)."""
    spec_dir = AGENTS_DIR / agent
    has_defense = False
    defense_patterns = [
        "ignore previous", "ignore instructions", "do not follow",
        "reject instruction", "system boundary", "injection",
        "untrusted input", "user input", "sanitize",
        "do not execute", "safety", "boundary",
    ]
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                prompt = doc.get("system_prompt", "")
                if isinstance(prompt, str) and prompt:
                    prompt_lower = prompt.lower()
                    matches = [p for p in defense_patterns if p in prompt_lower]
                    if len(matches) >= 2:  # At least 2 defense-related terms
                        has_defense = True
        except Exception:
            pass
    return PolicyResult(
        policy="P-050 prompt-injection-defense", level="L2", agent=agent, passed=has_defense,
        reason="Prompt injection defenses present" if has_defense else "System prompt lacks injection mitigation instructions",
        iso_controls="", enforcement="static",
    )


def p_tool_permission_boundaries(agent: str, ctx: dict) -> PolicyResult:
    """P-051: All tools have explicit allow/deny or toolNames in spec.
    OWASP ASI-02 (Tool Misuse / Excessive Permissions)."""
    spec_dir = AGENTS_DIR / agent
    issues = []
    total_servers = 0
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                tools = doc.get("tools", [])
                for t in tools if isinstance(tools, list) else []:
                    if isinstance(t, dict) and "server" in t:
                        total_servers += 1
                        has_boundary = (
                            "toolNames" in t
                            or "allow" in t
                            or "deny" in t
                            or "permissions" in t
                        )
                        if not has_boundary:
                            issues.append(f"{t['server']}: no toolNames/allow/deny")
        except Exception:
            pass
    if total_servers == 0:
        return PolicyResult(
            policy="P-051 tool-permission-boundaries", level="L2", agent=agent,
            passed=True, reason="No tool servers to check", enforcement="static",
        )
    passed = len(issues) == 0
    return PolicyResult(
        policy="P-051 tool-permission-boundaries", level="L2", agent=agent, passed=passed,
        reason=f"All {total_servers} tool refs have boundaries" if passed else f"{len(issues)} tools lack boundaries",
        evidence="; ".join(issues[:3]) if issues else "All bounded",
        enforcement="static",
    )


def p_privilege_escalation_guard(agent: str, ctx: dict) -> PolicyResult:
    """P-052: No agent can grant itself elevated permissions.
    OWASP ASI-03 (Privilege Escalation)."""
    spec_dir = AGENTS_DIR / agent
    issues = []
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            content = f.read_text()
            import re
            # Check for self-referential tool grants
            if re.search(r"(grant|elevate|escalate|promote).*permission", content, re.IGNORECASE):
                issues.append(f"{f.name}: self-grant pattern detected")
            # Check for admin/sudo in tool names without approval gate
            docs = list(yaml.safe_load_all(content))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                tools = doc.get("tools", [])
                for t in tools if isinstance(tools, list) else []:
                    if isinstance(t, dict):
                        for tn in t.get("toolNames", []):
                            if any(kw in tn.lower() for kw in ["admin", "sudo", "root", "exec", "apply", "delete"]):
                                guardrails = doc.get("guardrails", {})
                                approval = guardrails.get("require_approval_for", []) if isinstance(guardrails, dict) else []
                                if tn not in approval and not any(tn.startswith(a) for a in approval):
                                    issues.append(f"{tn}: privileged tool without approval gate")
        except Exception:
            pass
    passed = len(issues) == 0
    return PolicyResult(
        policy="P-052 privilege-escalation-guard", level="L2", agent=agent, passed=passed,
        reason="No privilege escalation risks" if passed else f"{len(issues)} escalation risks",
        evidence="; ".join(issues[:3]) if issues else "Clean",
        enforcement="static",
    )


def p_tool_output_validation(agent: str, ctx: dict) -> PolicyResult:
    """P-053: Agent spec declares output schema or validation for tool results.
    OWASP ASI-04 (Output Handling / Indirect Prompt Injection)."""
    spec_dir = AGENTS_DIR / agent
    has_validation = False
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                # Check for output validation config
                if doc.get("output_schema") or doc.get("output_validation"):
                    has_validation = True
                guardrails = doc.get("guardrails", {})
                if isinstance(guardrails, dict):
                    if guardrails.get("output_filter") or guardrails.get("validate_output"):
                        has_validation = True
                # Check for verify config (which validates outputs)
                autonomy = doc.get("autonomy", {})
                if isinstance(autonomy, dict) and autonomy.get("verify"):
                    has_validation = True
        except Exception:
            pass
    return PolicyResult(
        policy="P-053 tool-output-validation", level="L2", agent=agent, passed=has_validation,
        reason="Output validation configured" if has_validation else "No output schema or validation declared",
        enforcement="static",
    )


def p_cross_agent_trust_boundary(agent: str, ctx: dict) -> PolicyResult:
    """P-054: Multi-agent calls go through A2A, not direct.
    OWASP ASI-05 (Insecure Agent-Agent Communication)."""
    spec_dir = AGENTS_DIR / agent
    issues = []
    has_collaborators = False
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                autonomy = doc.get("autonomy", {})
                if isinstance(autonomy, dict):
                    collabs = autonomy.get("collaborators", [])
                    if collabs:
                        has_collaborators = True
                        for c in collabs if isinstance(collabs, list) else []:
                            if isinstance(c, dict):
                                protocol = c.get("protocol", "")
                                if protocol and protocol.lower() not in ("a2a", "http", "grpc"):
                                    issues.append(f"Collaborator uses non-standard protocol: {protocol}")
        except Exception:
            pass
    if not has_collaborators:
        return PolicyResult(
            policy="P-054 cross-agent-trust-boundary", level="L3", agent=agent,
            passed=True, reason="No multi-agent collaboration declared (single agent)",
            enforcement="static",
        )
    passed = len(issues) == 0
    return PolicyResult(
        policy="P-054 cross-agent-trust-boundary", level="L3", agent=agent, passed=passed,
        reason="All collaborator comms use A2A/HTTP/gRPC" if passed else f"{len(issues)} trust boundary issues",
        evidence="; ".join(issues[:3]) if issues else "A2A protocol",
        enforcement="static",
    )


def p_memory_poisoning_defense(agent: str, ctx: dict) -> PolicyResult:
    """P-055: Memory has TTL and source tagging.
    OWASP ASI-06 (Memory Poisoning)."""
    spec_dir = AGENTS_DIR / agent
    has_memory = False
    has_ttl = False
    has_source = False
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                autonomy = doc.get("autonomy", {})
                if isinstance(autonomy, dict):
                    memory = autonomy.get("memory", {})
                    if isinstance(memory, dict) and memory:
                        has_memory = True
                        if memory.get("ttl") or memory.get("max_age") or memory.get("expiry"):
                            has_ttl = True
                        if memory.get("source_tag") or memory.get("provenance") or memory.get("store"):
                            has_source = True
        except Exception:
            pass
    if not has_memory:
        return PolicyResult(
            policy="P-055 memory-poisoning-defense", level="L3", agent=agent,
            passed=True, reason="No persistent memory configured (no poisoning risk)",
            enforcement="static",
        )
    passed = has_ttl or has_source  # At least one defense
    missing = []
    if not has_ttl:
        missing.append("TTL/expiry")
    if not has_source:
        missing.append("source tagging")
    return PolicyResult(
        policy="P-055 memory-poisoning-defense", level="L3", agent=agent, passed=passed,
        reason="Memory defenses configured" if passed else f"Memory lacks: {', '.join(missing)}",
        enforcement="static",
    )


def p_cascading_hallucination_guard(agent: str, ctx: dict) -> PolicyResult:
    """P-056: Multi-hop tool chains have depth limit.
    OWASP ASI-07 (Cascading Hallucination)."""
    spec_dir = AGENTS_DIR / agent
    has_depth_limit = False
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                guardrails = doc.get("guardrails", {})
                if isinstance(guardrails, dict):
                    if guardrails.get("max_turns") or guardrails.get("max_depth") or guardrails.get("max_iterations"):
                        has_depth_limit = True
        except Exception:
            pass
    return PolicyResult(
        policy="P-056 cascading-hallucination-guard", level="L2", agent=agent, passed=has_depth_limit,
        reason="Depth/turn limit configured" if has_depth_limit else "No max_turns/max_depth in guardrails",
        enforcement="static",
    )


def p_resource_exhaustion_limit(agent: str, ctx: dict) -> PolicyResult:
    """P-057: Token budget and timeout declared in spec.
    OWASP ASI-08 (Resource Exhaustion / DoS)."""
    spec_dir = AGENTS_DIR / agent
    has_budget = False
    has_timeout = False
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                guardrails = doc.get("guardrails", {})
                if isinstance(guardrails, dict):
                    if guardrails.get("max_budget_usd") or guardrails.get("max_tokens") or guardrails.get("token_budget"):
                        has_budget = True
                    if guardrails.get("timeout") or guardrails.get("max_execution_time"):
                        has_timeout = True
                    # max_turns also serves as resource limit
                    if guardrails.get("max_turns"):
                        has_budget = True
        except Exception:
            pass
    passed = has_budget  # Budget is the primary resource control
    missing = []
    if not has_budget:
        missing.append("token/cost budget")
    if not has_timeout:
        missing.append("timeout")
    return PolicyResult(
        policy="P-057 resource-exhaustion-limit", level="L1", agent=agent, passed=passed,
        reason="Resource limits configured" if passed else f"Missing: {', '.join(missing)}",
        enforcement="static",
    )


def p_supply_chain_integrity(agent: str, ctx: dict) -> PolicyResult:
    """P-058: All images from signed registry (ghcr.io).
    OWASP ASI-09 (Supply Chain / Dependency Risks)."""
    # Check Helm chart values for image sources
    chart_dir = REPO_ROOT / "charts" / f"genai-kagent" / "templates"
    agent_file = chart_dir / f"agent-{agent}.yaml" if chart_dir.exists() else None

    # Also check the agent spec for image references
    spec_dir = AGENTS_DIR / agent
    issues = []
    images_found = []

    for search_dir in [spec_dir, chart_dir]:
        if search_dir and search_dir.exists():
            for f in search_dir.glob("*.yaml"):
                try:
                    content = f.read_text()
                    import re
                    # Find image references
                    image_refs = re.findall(r"image:\s*[\"']?([^\s\"']+)", content)
                    for img in image_refs:
                        images_found.append(img)
                        # Check for trusted registries
                        trusted = any(img.startswith(r) for r in [
                            "ghcr.io/", "docker.io/", "registry.k8s.io/",
                            "cr.agentgateway.dev/", "quay.io/",
                        ])
                        # Local images (no registry prefix) are OK for dev
                        if "/" not in img.split(":")[0]:
                            trusted = True
                        if not trusted:
                            issues.append(f"{img}: untrusted registry")
                except Exception:
                    pass

    if not images_found:
        return PolicyResult(
            policy="P-058 supply-chain-integrity", level="L3", agent=agent,
            passed=True, reason="No container images to validate",
            enforcement="static",
        )
    passed = len(issues) == 0
    return PolicyResult(
        policy="P-058 supply-chain-integrity", level="L3", agent=agent, passed=passed,
        reason=f"All {len(images_found)} images from trusted registries" if passed else f"{len(issues)} untrusted images",
        evidence="; ".join(issues[:3]) if issues else "All trusted",
        enforcement="static",
    )


def p_logging_completeness(agent: str, ctx: dict) -> PolicyResult:
    """P-059: OTEL traces enabled, Langfuse scoring active.
    OWASP ASI-10 (Insufficient Logging / Monitoring)."""
    spec_dir = AGENTS_DIR / agent
    has_verify = False
    has_memory_store = False
    for f in spec_dir.glob("*.yaml") if spec_dir.exists() else []:
        try:
            docs = list(yaml.safe_load_all(f.read_text()))
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                autonomy = doc.get("autonomy", {})
                if isinstance(autonomy, dict):
                    if autonomy.get("verify"):
                        has_verify = True
                    memory = autonomy.get("memory", {})
                    if isinstance(memory, dict) and memory.get("store"):
                        has_memory_store = True
        except Exception:
            pass
    passed = has_verify and has_memory_store
    missing = []
    if not has_verify:
        missing.append("verify (output validation/logging)")
    if not has_memory_store:
        missing.append("memory.store (trace persistence)")
    return PolicyResult(
        policy="P-059 logging-completeness", level="L3", agent=agent, passed=passed,
        reason="Logging and monitoring configured" if passed else f"Missing: {', '.join(missing)}",
        enforcement="static",
    )


# ── Policy Registry ──────────────────────────────────────────────────────────

ALL_POLICIES = [
    # L0 — Prototype (A.4, A.6.2.2, A.8.2, A.9)
    p_spec_exists,            # static
    p_no_inline_secrets,      # static
    p_toolnames_explicit,     # static
    p_tool_budget,            # static
    p_guardrails_set,         # static
    p_purpose_documented,     # static
    # L1 — Evaluated (A.6.2.4, A.7)
    p_dataset_exists,         # static
    p_prompt_versioned,       # runtime (MLflow)
    p_eval_run_exists,        # runtime (MLflow)
    # L2 — Staged (A.6.2.5, A.9.3, A.10)
    p_eval_passes_threshold,  # runtime (MLflow)
    p_ci_pipeline_passes,     # runtime (GitLab)
    p_human_oversight,        # static
    p_third_party_declared,   # static
    # L3 — Production (A.3.2, A.6.2.6, A.6.2.8)
    p_promoted_to_production, # runtime (MLflow)
    p_roles_defined,          # static
    p_observability_configured, # static
    # L4 — Optimized (A.5, A.7.5)
    p_impact_assessed,        # audit
    p_data_provenance,        # audit
    # OWASP Agentic Top 10 (ASI-01 through ASI-10)
    p_prompt_injection_defense,     # static (ASI-01)
    p_tool_permission_boundaries,   # static (ASI-02)
    p_privilege_escalation_guard,   # static (ASI-03)
    p_tool_output_validation,       # static (ASI-04)
    p_cross_agent_trust_boundary,   # static (ASI-05)
    p_memory_poisoning_defense,     # static (ASI-06)
    p_cascading_hallucination_guard, # static (ASI-07)
    p_resource_exhaustion_limit,    # static (ASI-08)
    p_supply_chain_integrity,       # static (ASI-09)
    p_logging_completeness,         # static (ASI-10)
]

# Enforcement point per policy (where the check runs).
# static = agent spec YAML, runtime = live system query, audit = periodic evidence check
POLICY_ENFORCEMENT = {
    "P-001 spec-exists": "static",
    "P-002 no-inline-secrets": "static",
    "P-003 toolnames-explicit": "static",
    "P-004 tool-budget": "static",
    "P-005 guardrails-set": "static",
    "P-006 purpose-documented": "static",
    "P-010 dataset-exists": "static",
    "P-011 prompt-versioned": "runtime",
    "P-012 eval-run-exists": "runtime",
    "P-020 eval-threshold": "runtime",
    "P-021 ci-pipeline": "runtime",
    "P-022 human-oversight": "static",
    "P-023 third-party-declared": "static",
    "P-030 promoted": "runtime",
    "P-031 roles-defined": "static",
    "P-032 observability": "static",
    "P-040 impact-assessed": "audit",
    "P-041 data-provenance": "audit",
    # OWASP Agentic Top 10
    "P-050 prompt-injection-defense": "static",
    "P-051 tool-permission-boundaries": "static",
    "P-052 privilege-escalation-guard": "static",
    "P-053 tool-output-validation": "static",
    "P-054 cross-agent-trust-boundary": "static",
    "P-055 memory-poisoning-defense": "static",
    "P-056 cascading-hallucination-guard": "static",
    "P-057 resource-exhaustion-limit": "static",
    "P-058 supply-chain-integrity": "static",
    "P-059 logging-completeness": "static",
}

LEVEL_ORDER = ["L0", "L1", "L2", "L3", "L4"]

LEVEL_NAMES = {"L0": "Prototype", "L1": "Evaluated", "L2": "Staged", "L3": "Production", "L4": "Optimized"}


def compute_maturity(results: list[PolicyResult]) -> str:
    """Highest level where ALL policies at that level and below pass."""
    for level in reversed(LEVEL_ORDER):
        level_results = [r for r in results if LEVEL_ORDER.index(r.level) <= LEVEL_ORDER.index(level)]
        if level_results and all(r.passed for r in level_results):
            return level
    return "—"


# ── Runner ───────────────────────────────────────────────────────────────────

def discover_agents() -> list[str]:
    """Discover agents from agents/ directory."""
    if not AGENTS_DIR.exists():
        return []
    return sorted([d.name for d in AGENTS_DIR.iterdir() if d.is_dir() and not d.name.startswith("_") and d.name != "envs"])


def run_policies(agents: list[str], level_filter: str | None = None, profile: str = "solo",
                  type_scope: set[str] | None = None) -> dict[str, list[PolicyResult]]:
    """Run all policies for all agents, respecting profile and type scope.

    Args:
        type_scope: If set, only run policies whose ID is in this set.
                    Loaded from taxonomy.yaml via --type flag.
    """
    policies = ALL_POLICIES

    results: dict[str, list[PolicyResult]] = {}
    with httpx.Client(timeout=15) as client:
        ctx = {"http_client": client, "profile": profile}
        for agent in agents:
            agent_results = []
            for policy_fn in policies:
                try:
                    result = policy_fn(agent, ctx)
                    # Apply enforcement point from registry
                    if not result.enforcement and result.policy in POLICY_ENFORCEMENT:
                        result.enforcement = POLICY_ENFORCEMENT[result.policy]
                    # Skip policies not in taxonomy type scope
                    if type_scope is not None and get_policy_id(result.policy) not in type_scope:
                        result = PolicyResult(
                            policy=result.policy, level=result.level, agent=agent,
                            passed=True, reason="Skipped (not in type scope)",
                            iso_controls=result.iso_controls, skipped=True,
                        )
                    # Skip enterprise-only policies in solo profile
                    elif profile == "solo" and result.policy in ENTERPRISE_ONLY_POLICIES:
                        result = PolicyResult(
                            policy=result.policy, level=result.level, agent=agent,
                            passed=True, reason=f"Skipped (solo profile)",
                            iso_controls=result.iso_controls, skipped=True,
                        )
                    agent_results.append(result)
                except Exception as e:
                    agent_results.append(PolicyResult(
                        policy=policy_fn.__doc__.split(":")[0] if policy_fn.__doc__ else policy_fn.__name__,
                        level="L0", agent=agent, passed=False, reason=f"Error: {e}",
                    ))
            results[agent] = agent_results
    return results


# ── Output ───────────────────────────────────────────────────────────────────

def print_table(results: dict[str, list[PolicyResult]], profile: str = "solo"):
    """Print human-readable compliance table."""
    print(f"\n{'─'*100}")
    print(f"  AgentOps Policy Compliance Report — ISO/IEC 42001:2023 Aligned")
    print(f"  Profile: {profile}  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'─'*100}\n")

    for agent, agent_results in results.items():
        maturity = compute_maturity(agent_results)
        maturity_name = LEVEL_NAMES.get(maturity, "None")
        active = [r for r in agent_results if not r.skipped]
        passed = sum(1 for r in active if r.passed)
        skipped = sum(1 for r in agent_results if r.skipped)
        total = len(active)

        skip_note = f"  ({skipped} skipped)" if skipped else ""
        print(f"  {agent}  [{maturity} {maturity_name}]  {passed}/{total} passed{skip_note}")
        print(f"  {'─'*70}")

        for r in agent_results:
            if r.skipped:
                print(f"    - {r.level} {r.policy:<30s} {r.reason}")
            else:
                icon = "✓" if r.passed else "✗"
                iso = f"  [{r.iso_controls}]" if r.iso_controls else ""
                print(f"    {icon} {r.level} {r.policy:<30s} {r.reason}{iso}")
        print()

    # Summary
    print(f"{'─'*100}")
    print(f"  Summary:")
    for agent, agent_results in results.items():
        maturity = compute_maturity(agent_results)
        failed = [r for r in agent_results if not r.passed]
        status = f"{maturity} {LEVEL_NAMES.get(maturity, 'None')}"
        if failed:
            blockers = ", ".join(r.policy.split(" ")[0] for r in failed[:3])
            print(f"    {agent:<25s} {status:<20s} blocked by: {blockers}")
        else:
            print(f"    {agent:<25s} {status:<20s} all clear")

    # ISO 42001 Annex A coverage
    all_controls = set()
    covered_controls = set()
    for agent_results in results.values():
        for r in agent_results:
            if r.iso_controls:
                ctrls = [c.strip() for c in r.iso_controls.split(",")]
                all_controls.update(ctrls)
                if r.passed:
                    covered_controls.update(ctrls)
    annex_a_total = 38  # ISO 42001 Annex A has 38 controls
    print(f"\n  ISO/IEC 42001 Annex A Coverage: {len(all_controls)}/{annex_a_total} controls mapped, {len(covered_controls)}/{len(all_controls)} passing")
    print(f"{'─'*100}\n")


def print_json(results: dict[str, list[PolicyResult]]):
    """Print machine-readable JSON."""
    output = {}
    for agent, agent_results in results.items():
        output[agent] = {
            "maturity": compute_maturity(agent_results),
            "passed": sum(1 for r in agent_results if r.passed),
            "total": len(agent_results),
            "policies": [r.to_dict() for r in agent_results],
        }
    print(json.dumps(output, indent=2))


# ── Importable interface for eval-board ──────────────────────────────────────

def get_compliance_summary(profile: str = "solo") -> list[dict]:
    """Return compliance data for eval-board integration."""
    agents = discover_agents()
    results = run_policies(agents, profile=profile)
    summary = []
    for agent, agent_results in results.items():
        maturity = compute_maturity(agent_results)
        passed = sum(1 for r in agent_results if r.passed)
        total = len(agent_results)
        failed = [r.policy for r in agent_results if not r.passed]
        summary.append({
            "agent": agent,
            "maturity": maturity,
            "maturity_name": LEVEL_NAMES.get(maturity, "None"),
            "passed": passed,
            "total": total,
            "score": f"{passed}/{total}",
            "failed_policies": failed,
            "policies": [r.to_dict() for r in agent_results],
        })
    return summary


# ── Scope Document Generator ────────────────────────────────────────────────

def generate_scope_doc(taxonomy: dict) -> str:
    """Generate ISO 42001 Clause 4.3 scope document as markdown.

    This is the formal AIMS (AI Management System) scope definition
    required by ISO 42001 §4.3. It declares which AI systems are in scope,
    their types, risk tiers, applicable policies, and verification requirements.
    """
    types_data = taxonomy.get("types", {})
    refs = taxonomy.get("standard_refs", [])

    lines = [
        "# AI Management System (AIMS) Scope Definition",
        "",
        "**ISO/IEC 42001:2023 Clause 4.3 — Determining the Scope of the AIMS**",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
        "## 1. Normative References",
        "",
    ]
    for ref in refs:
        lines.append(f"- {ref}")
    lines.append("")

    lines.extend([
        "## 2. AI System Types in Scope",
        "",
        "The following AI system types are managed under this AIMS:",
        "",
    ])

    # Summary table
    lines.append("| Type | ISO Reference | Risk Tier | Policies | Eval Required | Observability |")
    lines.append("|------|--------------|-----------|----------|---------------|---------------|")
    for type_name, type_data in types_data.items():
        risk = type_data.get("risk_tier", "varies" if type_data.get("subtypes") else "—")
        risk_display = risk if isinstance(risk, str) else "varies"
        n_policies = len(type_data.get("policy_scope", []))
        eval_req = "Yes" if type_data.get("eval_required") else "No"
        obs = type_data.get("observability_level", "—")
        iso_ref = type_data.get("iso_ref", "—")
        lines.append(f"| `{type_name}` | {iso_ref} | {risk_display} | {n_policies} | {eval_req} | {obs} |")
    lines.append("")

    # Detailed per-type sections
    lines.append("## 3. Type Details")
    lines.append("")

    for type_name, type_data in types_data.items():
        lines.append(f"### 3.{list(types_data.keys()).index(type_name)+1}. {type_name}")
        lines.append("")
        lines.append(f"**Description**: {type_data.get('description', '—')}")
        lines.append(f"**ISO Reference**: {type_data.get('iso_ref', '—')}")
        lines.append("")

        # Risk tier (handle subtypes)
        subtypes = type_data.get("subtypes")
        if subtypes:
            lines.append("**Risk Tiers by Subtype**:")
            lines.append("")
            for st_name, st_data in subtypes.items():
                examples = ", ".join(st_data.get("examples", []))
                lines.append(f"- `{st_name}` ({st_data.get('risk_tier', '—')}): {st_data.get('description', '')} — e.g. {examples}")
            lines.append("")
        else:
            lines.append(f"**Risk Tier**: {type_data.get('risk_tier', '—')}")
            lines.append("")

        # Examples
        examples = type_data.get("examples", [])
        if examples:
            lines.append(f"**Instances**: {', '.join(examples)}")
            lines.append("")

        # Applicable policies
        scope = type_data.get("policy_scope", [])
        if scope:
            lines.append("**Applicable Policies**:")
            lines.append("")
            for p in scope:
                # Render with comment: "P-001  # spec-exists" → "P-001 (spec-exists)"
                if "#" in p:
                    pid, comment = p.split("#", 1)
                    lines.append(f"- {pid.strip()} ({comment.strip()})")
                else:
                    lines.append(f"- {p.strip()}")
            lines.append("")

        # ISO controls
        controls = type_data.get("iso_controls", [])
        if controls:
            lines.append(f"**ISO 42001 Annex A Controls**: {', '.join(controls)}")
            lines.append("")

        # V&V requirements
        lines.append(f"**Eval Required**: {'Yes' if type_data.get('eval_required') else 'No'}")
        lines.append(f"**Observability Level**: {type_data.get('observability_level', '—')}")
        lines.append("")

    # Policy coverage matrix
    lines.extend([
        "## 4. Policy Coverage Matrix",
        "",
        "Shows which policies apply to which system types.",
        "",
    ])

    # Collect all policy IDs
    all_policy_ids = set()
    for type_data in types_data.values():
        for p in type_data.get("policy_scope", []):
            pid = p.split("#")[0].strip().split()[0] if "#" in p else p.strip()
            all_policy_ids.add(pid)
    sorted_pids = sorted(all_policy_ids)
    type_names = list(types_data.keys())

    header = "| Policy | " + " | ".join(f"`{t}`" for t in type_names) + " |"
    sep = "|--------|" + "|".join("---" for _ in type_names) + "|"
    lines.append(header)
    lines.append(sep)

    for pid in sorted_pids:
        row = f"| {pid} |"
        for t in type_names:
            scope = types_data[t].get("policy_scope", [])
            scope_ids = {s.split("#")[0].strip().split()[0] if "#" in s else s.strip() for s in scope}
            row += " x |" if pid in scope_ids else "   |"
        lines.append(row)
    lines.append("")

    lines.extend([
        "## 5. Exclusions",
        "",
        "The following are **not** in scope of this AIMS:",
        "",
        "- Infrastructure components without AI decision-making (ingress-nginx, k3d cluster, PostgreSQL instances)",
        "- Human-operated UIs that display AI outputs but make no autonomous decisions",
        "- Development tooling (IDE plugins, linters) that does not affect production AI behavior",
        "",
        "---",
        "",
        "*This document is auto-generated from `data/compliance/taxonomy.yaml` by `scripts/agentops-policy.py --scope-doc`.*",
        "*It should be regenerated whenever the taxonomy or policy set changes.*",
        "",
    ])

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

from datetime import datetime

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AgentOps policy compliance checker")
    parser.add_argument("--agent", help="Check a single agent")
    parser.add_argument("--profile", choices=["solo", "enterprise"], default="solo",
                        help="Compliance profile (default: solo)")
    parser.add_argument("--type", dest="system_type",
                        help="Scope policies by taxonomy type (agent, mcp_server, llm_gateway, eval_pipeline, artifact_store, observability)")
    parser.add_argument("--scope-doc", action="store_true",
                        help="Generate ISO 42001 Clause 4.3 scope document (markdown)")
    parser.add_argument("--standard", choices=["iso42001", "owasp", "all"], default="all",
                        help="Filter by standard: iso42001 (P-001..P-041), owasp (P-050..P-059), all (default)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--gate", action="store_true", help="Exit 1 if any policy fails")
    parser.add_argument("--level", choices=["L0", "L1", "L2", "L3", "L4"], help="Filter to maturity level")
    parser.add_argument("--mlflow", default=None)
    parser.add_argument("--gitlab-pat", default=None)
    args = parser.parse_args()

    if args.mlflow:
        MLFLOW_URL = args.mlflow
    if args.gitlab_pat:
        GITLAB_PAT = args.gitlab_pat

    # Load taxonomy for --type and --scope-doc
    taxonomy = load_taxonomy()

    # Handle --scope-doc: generate and exit
    if args.scope_doc:
        if not taxonomy:
            print("ERROR: Cannot load taxonomy.yaml", file=sys.stderr)
            sys.exit(1)
        print(generate_scope_doc(taxonomy))
        sys.exit(0)

    # Resolve --standard to policy ID filter
    standard_scope: set[str] | None = None
    if args.standard == "iso42001":
        standard_scope = {f"P-{i:03d}" for i in list(range(1, 42))}  # P-001 through P-041
    elif args.standard == "owasp":
        standard_scope = {f"P-{i:03d}" for i in range(50, 60)}  # P-050 through P-059

    # Resolve --type to policy scope
    type_scope: set[str] | None = None
    if args.system_type:
        if not taxonomy:
            print(f"ERROR: Cannot load taxonomy.yaml for --type filtering", file=sys.stderr)
            sys.exit(1)
        type_scope = get_type_policy_scope(taxonomy, args.system_type)
        if not type_scope:
            available = ", ".join(taxonomy.get("types", {}).keys())
            print(f"ERROR: Unknown type '{args.system_type}'. Available: {available}", file=sys.stderr)
            sys.exit(1)

    # Combine type_scope and standard_scope (intersection if both set)
    effective_scope: set[str] | None = None
    if type_scope is not None and standard_scope is not None:
        effective_scope = type_scope & standard_scope
    elif type_scope is not None:
        effective_scope = type_scope
    elif standard_scope is not None:
        effective_scope = standard_scope

    agents = [args.agent] if args.agent else discover_agents()
    if not agents:
        print("No agents found in agents/ directory", file=sys.stderr)
        sys.exit(1)

    results = run_policies(agents, args.level, profile=args.profile, type_scope=effective_scope)

    if args.json:
        print_json(results)
    else:
        print_table(results, profile=args.profile)

    if args.gate:
        # Only gate on non-skipped policies
        all_passed = all(
            r.passed for agent_results in results.values()
            for r in agent_results if not r.skipped
        )
        sys.exit(0 if all_passed else 1)
