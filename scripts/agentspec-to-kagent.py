#!/usr/bin/env python3
"""Transpile Agent Spec YAML → kagent CRDs.

Reads agents/{name}/agent.yaml (Oracle Agent Spec v26.x format) and
emits kagent v1alpha2 CRDs (Agent, ModelConfig, RemoteMCPServer) into
charts/genai-kagent/templates/.

Usage:
    # Transpile all agents
    uv run scripts/agentspec-to-kagent.py

    # Transpile specific agent
    uv run scripts/agentspec-to-kagent.py mlops

    # Dry-run (print to stdout, don't write files)
    uv run scripts/agentspec-to-kagent.py --dry-run

    # Custom paths
    uv run scripts/agentspec-to-kagent.py --agents-dir agents/ --output-dir charts/genai-kagent/templates/
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path
from typing import Any

# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///

import yaml


# ── Skill → A2A skill mapping ──────────────────────────────────────
# Maps agent-spec skill IDs to A2A skill card entries.
# Source of truth: agents/_shared/ + agent YAML capabilities.
SKILL_CATALOG: dict[str, dict[str, Any]] = {
    "kubernetes-ops": {
        "id": "kubernetes-ops",
        "name": "Kubernetes Operations",
        "description": "Manage Kubernetes resources — get, describe, logs, apply, delete",
        "tags": ["platform", "kubernetes"],
    },
    "mlflow-tracking": {
        "id": "experiment-tracking",
        "name": "Experiment Tracking",
        "description": "Track, compare, and manage ML experiments using MLflow",
        "tags": ["mlops", "mlflow", "experiments"],
    },
    "dev-sandbox": {
        "id": "code-execution",
        "name": "Sandboxed Code Execution",
        "description": "Run code in ephemeral Kubernetes jobs",
        "tags": ["development", "sandbox"],
    },
    "code-generation": {
        "id": "code-generation",
        "name": "Code Generation",
        "description": "Generate production-quality code from specifications",
        "tags": ["development", "generation"],
    },
    "documentation": {
        "id": "documentation",
        "name": "Documentation",
        "description": "Generate docstrings, README, and API documentation",
        "tags": ["development", "documentation"],
    },
    "security-audit": {
        "id": "security-audit",
        "name": "Security Audit",
        "description": "Audit code for OWASP Top 10 vulnerabilities",
        "tags": ["development", "security"],
    },
    "n8n-workflow-ops": {
        "id": "workflow-management",
        "name": "Workflow Management",
        "description": "Manage n8n workflows — list, activate, execute",
        "tags": ["platform", "workflows", "n8n"],
    },
    "gitlab-pipeline-ops": {
        "id": "ci-cd-pipelines",
        "name": "CI/CD Pipelines",
        "description": "Manage GitLab pipelines, MRs, and repository operations",
        "tags": ["platform", "ci-cd", "gitlab"],
    },
}

# Maps agent-spec skill names → kagent RemoteMCPServer names
SKILL_TO_MCP: dict[str, str] = {
    "kubernetes-ops": "kubernetes-ops",
    "mlflow-tracking": "kubernetes-ops",  # MLflow accessed via k8s
    "n8n-workflow-ops": "n8n-workflow-ops",
    "gitlab-pipeline-ops": "gitlab-ops",
    "dev-sandbox": "kubernetes-ops",
}

# ── MCP server definitions ─────────────────────────────────────────
MCP_SERVERS: dict[str, dict[str, str]] = {
    "kubernetes-ops": {
        "description": "Kubernetes cluster management — kubectl get/describe/logs/apply",
        "url": "http://genai-mcp-kubernetes.genai.svc.cluster.local:3000/mcp",
    },
    "n8n-workflow-ops": {
        "description": "n8n workflow management and execution",
        "url": "http://genai-mcp-n8n.genai.svc.cluster.local:3000/mcp",
    },
    "gitlab-ops": {
        "description": "GitLab repository, MR, and pipeline management",
        "url": "http://genai-mcp-gitlab.genai.svc.cluster.local:3000/mcp",
    },
    "datahub-metadata": {
        "description": "DataHub metadata catalog — search datasets, pipelines, lineage",
        "url": "http://genai-mcp-datahub.genai.svc.cluster.local:3000/mcp",
    },
    "plane-project": {
        "description": "Plane project management — issues, cycles, modules",
        "url": "http://genai-mcp-plane.genai.svc.cluster.local:3000/mcp",
    },
}


def load_agent_spec(path: Path) -> dict[str, Any]:
    """Load and validate an Agent Spec YAML file."""
    with open(path) as f:
        spec = yaml.safe_load(f)

    if spec.get("component_type") != "Agent":
        raise ValueError(f"{path}: component_type must be 'Agent', got '{spec.get('component_type')}'")

    required = ["name", "description", "system_prompt"]
    for key in required:
        if key not in spec:
            raise ValueError(f"{path}: missing required field '{key}'")

    return spec


def agent_to_crd(spec: dict[str, Any], namespace_tpl: str = "{{ .Release.Namespace }}") -> dict[str, Any]:
    """Convert Agent Spec → kagent Agent CRD."""
    name = spec["name"]
    skills = spec.get("skills", [])

    # Build A2A skills from skill catalog
    a2a_skills = []
    for skill_id in skills:
        if skill_id in SKILL_CATALOG:
            a2a_skills.append(SKILL_CATALOG[skill_id])
        else:
            # Generate a default entry for unknown skills
            a2a_skills.append({
                "id": skill_id,
                "name": skill_id.replace("-", " ").title(),
                "description": f"Skill: {skill_id}",
                "tags": spec.get("metadata", {}).get("tags", []),
            })

    # Collect MCP server refs for this agent
    tool_refs = []
    for skill_id in skills:
        if skill_id in SKILL_TO_MCP:
            mcp_name = SKILL_TO_MCP[skill_id]
            if mcp_name not in tool_refs:
                tool_refs.append(mcp_name)

    crd: dict[str, Any] = {
        "apiVersion": "kagent.dev/v1alpha2",
        "kind": "Agent",
        "metadata": {
            "name": f"{name}-agent",
            "namespace": namespace_tpl,
            "labels": {
                "app.kubernetes.io/managed-by": "agentspec-transpiler",
                "agentspec.oracle.com/version": spec.get("agentspec_version", "unknown"),
            },
            "annotations": {
                "agentspec.oracle.com/source": f"agents/{name}/agent.yaml",
            },
        },
        "spec": {
            "type": "Declarative",
            "description": spec["description"],
            "declarative": {
                "systemMessage": LiteralStr(spec["system_prompt"].rstrip()),
                "modelConfig": "default-model-config",
            },
        },
    }

    if a2a_skills:
        crd["spec"]["declarative"]["a2aConfig"] = {"skills": a2a_skills}

    if tool_refs:
        crd["spec"]["declarative"]["tools"] = [
            {"remoteMCPServer": ref} for ref in tool_refs
        ]

    return crd


class LiteralStr(str):
    """String that renders as YAML literal block (|)."""


def literal_representer(dumper: yaml.Dumper, data: LiteralStr) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(LiteralStr, literal_representer)


def render_agents_yaml(crds: list[dict[str, Any]]) -> str:
    """Render list of Agent CRDs to a multi-document YAML string."""
    header = textwrap.dedent("""\
        # ═══════════════════════════════════════════════════════
        # Auto-generated by scripts/agentspec-to-kagent.py
        # Source: agents/*/agent.yaml (Oracle Agent Spec v26.x)
        # DO NOT EDIT — run `task agents:transpile` to regenerate
        # ═══════════════════════════════════════════════════════
    """)
    docs = []
    for crd in crds:
        docs.append(yaml.dump(crd, default_flow_style=False, sort_keys=False, width=120, allow_unicode=True))
    return header + "---\n" + "---\n".join(docs)


def render_mcp_servers_yaml(
    agent_specs: list[dict[str, Any]],
    namespace_tpl: str = "{{ .Release.Namespace }}",
) -> str:
    """Render RemoteMCPServer CRDs for all MCP servers referenced by agents."""
    # Collect all referenced MCP servers across agents
    referenced: set[str] = set()
    for spec in agent_specs:
        for skill_id in spec.get("skills", []):
            if skill_id in SKILL_TO_MCP:
                referenced.add(SKILL_TO_MCP[skill_id])

    # Always include all known servers (some agents use them via gateway)
    all_servers = set(MCP_SERVERS.keys())
    servers_to_emit = all_servers  # Emit all — kagent needs them at startup

    header = textwrap.dedent("""\
        # ═══════════════════════════════════════════════════════
        # Auto-generated by scripts/agentspec-to-kagent.py
        # Source: MCP server registry in agentspec-to-kagent.py
        # DO NOT EDIT — run `task agents:transpile` to regenerate
        # ═══════════════════════════════════════════════════════
    """)

    crds = []
    for name in sorted(servers_to_emit):
        server = MCP_SERVERS[name]
        crd = {
            "apiVersion": "kagent.dev/v1alpha2",
            "kind": "RemoteMCPServer",
            "metadata": {
                "name": name,
                "namespace": namespace_tpl,
                "labels": {
                    "app.kubernetes.io/managed-by": "agentspec-transpiler",
                },
            },
            "spec": {
                "description": server["description"],
                "protocol": "STREAMABLE_HTTP",
                "url": server["url"],
                "timeout": "30s",
                "sseReadTimeout": "5m0s",
                "allowedNamespaces": {"from": "Same"},
            },
        }
        crds.append(yaml.dump(crd, default_flow_style=False, sort_keys=False, width=120, allow_unicode=True))

    return header + "---\n" + "---\n".join(crds)


def render_drift_report(
    agent_specs: list[dict[str, Any]],
    existing_agents_path: Path,
    existing_mcp_path: Path,
) -> str:
    """Compare agent specs vs existing CRDs and report drift."""
    lines = ["# Agent Spec → kagent Drift Report", ""]

    # Read existing CRDs (raw text — may contain Helm templates that break YAML parsing)
    existing_agents: set[str] = set()
    if existing_agents_path.exists():
        import re
        content = existing_agents_path.read_text()
        # Extract agent names from "name: xxx-agent" lines after "kind: Agent"
        for match in re.finditer(r"kind:\s+Agent\s*\n\s*metadata:\s*\n\s*name:\s*(\S+)", content):
            existing_agents.add(match.group(1))

    spec_agents = {f"{s['name']}-agent" for s in agent_specs}

    added = spec_agents - existing_agents
    removed = existing_agents - spec_agents
    common = spec_agents & existing_agents

    lines.append(f"Agents in spec: {len(spec_agents)}")
    lines.append(f"Agents in CRDs: {len(existing_agents)}")
    if added:
        lines.append(f"NEW (will be created): {', '.join(sorted(added))}")
    if removed:
        lines.append(f"ORPHANED (in CRDs but not in spec): {', '.join(sorted(removed))}")
    if common:
        lines.append(f"UPDATING: {', '.join(sorted(common))}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Transpile Agent Spec YAML → kagent CRDs")
    parser.add_argument("agents", nargs="*", help="Agent names to transpile (default: all)")
    parser.add_argument("--agents-dir", type=Path, default=Path("agents"), help="Agent definitions directory")
    parser.add_argument("--output-dir", type=Path, default=Path("charts/genai-kagent/templates"), help="Output directory for CRDs")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout instead of writing files")
    parser.add_argument("--drift", action="store_true", help="Show drift report only")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    agents_dir = repo_root / args.agents_dir
    output_dir = repo_root / args.output_dir

    # Discover agent specs
    agent_dirs = sorted(
        d for d in agents_dir.iterdir()
        if d.is_dir() and not d.name.startswith("_") and d.name != "envs"
    )

    if args.agents:
        agent_dirs = [d for d in agent_dirs if d.name in args.agents]
        if not agent_dirs:
            print(f"Error: no matching agents found for {args.agents}", file=sys.stderr)
            sys.exit(1)

    # Load all specs
    specs: list[dict[str, Any]] = []
    for agent_dir in agent_dirs:
        spec_path = agent_dir / "agent.yaml"
        if not spec_path.exists():
            print(f"Warning: {spec_path} not found, skipping", file=sys.stderr)
            continue
        try:
            spec = load_agent_spec(spec_path)
            specs.append(spec)
            print(f"  Loaded: {spec['name']} (v{spec.get('agentspec_version', '?')})")
        except (ValueError, yaml.YAMLError) as e:
            print(f"Error loading {spec_path}: {e}", file=sys.stderr)
            sys.exit(1)

    if not specs:
        print("No agent specs found.", file=sys.stderr)
        sys.exit(1)

    # Drift report mode
    if args.drift:
        report = render_drift_report(
            specs,
            output_dir / "custom-agents.yaml",
            output_dir / "remotemcpservers.yaml",
        )
        print(report)
        return

    # Transpile
    crds = [agent_to_crd(spec) for spec in specs]
    agents_yaml = render_agents_yaml(crds)
    mcp_yaml = render_mcp_servers_yaml(specs)

    if args.dry_run:
        print("=" * 60)
        print("custom-agents.yaml")
        print("=" * 60)
        print(agents_yaml)
        print()
        print("=" * 60)
        print("remotemcpservers.yaml")
        print("=" * 60)
        print(mcp_yaml)
        return

    # Write files
    agents_out = output_dir / "custom-agents.yaml"
    mcp_out = output_dir / "remotemcpservers.yaml"

    agents_out.write_text(agents_yaml)
    print(f"  Wrote: {agents_out.relative_to(repo_root)}")

    mcp_out.write_text(mcp_yaml)
    print(f"  Wrote: {mcp_out.relative_to(repo_root)}")

    print(f"\n  {len(crds)} agents, {len(MCP_SERVERS)} MCP servers transpiled.")
    print("  Commit + push for ArgoCD to sync.")


if __name__ == "__main__":
    main()
