#!/usr/bin/env python3
"""Lint kagent Agent CRDs against quality standards.

Validates Agent CRDs in charts/genai-kagent/templates/ for:
- Required fields and correct apiVersion/kind
- System message quality (length, no TODOs, no hardcoded URLs)
- Tool configuration (toolNames present on McpServer refs)
- ModelConfig references

Usage:
    python3 scripts/agent-lint.py                    # lint all agents in templates/
    python3 scripts/agent-lint.py --file path.yaml   # lint a single file
    python3 scripts/agent-lint.py --strict            # exit 1 on any warning
    python3 scripts/agent-lint.py --json              # JSON output
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml required. Install with: uv pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# ── Constants ────────────────────────────────────────────

EXPECTED_API_VERSION = "kagent.dev/v1alpha2"
EXPECTED_KIND = "Agent"
MIN_SYSTEM_MESSAGE_LENGTH = 100
HELM_TEMPLATE_RE = re.compile(r"\{\{.*?\}\}")
# Match IPs like 192.168.1.1 or http://10.0.0.1:8080 but not inside {{ }}
IP_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
URL_RE = re.compile(r"https?://[^\s\"']+")
TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)

DEFAULT_TEMPLATES_DIR = "charts/genai-kagent/templates"


# ── Data structures ──────────────────────────────────────

@dataclass
class LintMessage:
    level: str  # "error" | "warning"
    file: str
    agent: str
    message: str

    def to_dict(self) -> dict:
        return {"level": self.level, "file": self.file, "agent": self.agent, "message": self.message}


@dataclass
class AgentReport:
    name: str
    file: str
    passed: bool = True
    messages: list[LintMessage] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "file": self.file,
            "passed": self.passed,
            "messages": [m.to_dict() for m in self.messages],
        }


# ── Helpers ──────────────────────────────────────────────

def contains_helm_template(value: str) -> bool:
    """Check if a string contains Helm template syntax."""
    return bool(HELM_TEMPLATE_RE.search(str(value)))


def strip_helm_templates(value: str) -> str:
    """Remove Helm template expressions for content checking."""
    return HELM_TEMPLATE_RE.sub("", str(value))


def get_nested(d: dict, *keys, default=None):
    """Safely get a nested dict value."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


# ── Validators ───────────────────────────────────────────

def lint_agent(doc: dict, filepath: str) -> AgentReport:
    """Validate a single Agent CRD document."""
    name = get_nested(doc, "metadata", "name") or "<unknown>"
    report = AgentReport(name=name, file=filepath)

    def error(msg: str):
        report.passed = False
        report.messages.append(LintMessage("error", filepath, name, msg))

    def warn(msg: str):
        report.messages.append(LintMessage("warning", filepath, name, msg))

    # --- apiVersion ---
    api_version = doc.get("apiVersion", "")
    if contains_helm_template(str(api_version)):
        pass  # skip check if templated
    elif api_version != EXPECTED_API_VERSION:
        error(f"apiVersion must be '{EXPECTED_API_VERSION}', got '{api_version}'")

    # --- kind ---
    kind = doc.get("kind", "")
    if kind != EXPECTED_KIND:
        error(f"kind must be '{EXPECTED_KIND}', got '{kind}'")

    # --- metadata.name ---
    if not get_nested(doc, "metadata", "name"):
        error("metadata.name is required")

    # --- spec.declarative.systemMessage ---
    decl = get_nested(doc, "spec", "declarative") or {}
    sys_msg = decl.get("systemMessage", "")
    sys_msg_from = decl.get("systemMessageFrom")

    if not sys_msg and not sys_msg_from:
        error("spec.declarative.systemMessage (or systemMessageFrom) is required")
    elif sys_msg:
        if contains_helm_template(sys_msg):
            pass  # skip length/content checks for templated messages
        else:
            if len(sys_msg) < MIN_SYSTEM_MESSAGE_LENGTH:
                error(
                    f"systemMessage too short ({len(sys_msg)} chars, minimum {MIN_SYSTEM_MESSAGE_LENGTH})"
                )

            # Check for TODO/FIXME/HACK
            todo_matches = TODO_RE.findall(sys_msg)
            if todo_matches:
                error(f"systemMessage contains TODO/FIXME markers: {', '.join(todo_matches)}")

            # Check for hardcoded IPs (outside Helm templates)
            clean_msg = strip_helm_templates(sys_msg)
            ip_matches = IP_RE.findall(clean_msg)
            if ip_matches:
                warn(f"systemMessage contains hardcoded IP addresses: {', '.join(ip_matches)}")

            url_matches = URL_RE.findall(clean_msg)
            if url_matches:
                warn(f"systemMessage contains hardcoded URLs: {', '.join(url_matches)}")

    # --- spec.declarative.tools ---
    tools = decl.get("tools")
    if not tools or not isinstance(tools, list):
        error("spec.declarative.tools must be a non-empty array")
    elif len(tools) == 0:
        error("spec.declarative.tools must contain at least 1 tool")
    else:
        for i, tool in enumerate(tools):
            tool_type = tool.get("type", "")
            if tool_type == "McpServer":
                mcp = tool.get("mcpServer", {})
                mcp_name = mcp.get("name", f"tool[{i}]")
                tool_names = mcp.get("toolNames")
                if not tool_names or not isinstance(tool_names, list) or len(tool_names) == 0:
                    error(
                        f"McpServer tool '{mcp_name}' MUST have explicit toolNames "
                        f"(pods crash without this — see kagent v0.8.0 ValidationError)"
                    )

    # --- spec.declarative.modelConfig ---
    model_config = decl.get("modelConfig")
    if not model_config:
        error("spec.declarative.modelConfig is required")
    elif contains_helm_template(str(model_config)):
        pass  # skip if templated
    elif not isinstance(model_config, str) or len(model_config.strip()) == 0:
        error("spec.declarative.modelConfig must be a non-empty string")

    # --- Labels (warning, not error) ---
    labels = get_nested(doc, "metadata", "labels") or {}
    if "app.kubernetes.io/version" not in labels:
        warn("missing recommended label: app.kubernetes.io/version")

    return report


# ── File parsing ─────────────────────────────────────────

def parse_yaml_file(filepath: str) -> list[dict]:
    """Parse a YAML file, handling multi-document and Helm templates.

    Helm template expressions ({{ }}) are stripped for YAML parsing only,
    then the original values are used for content validation.
    """
    path = Path(filepath)
    if not path.exists():
        return []

    raw = path.read_text()

    # Replace Helm template expressions with safe placeholder strings for parsing
    # We need YAML to parse, but we want to preserve the structure
    # Strategy: replace {{ ... }} with a quoted placeholder
    sanitized = HELM_TEMPLATE_RE.sub("__HELM_TEMPLATE__", raw)

    docs = []
    try:
        for doc in yaml.safe_load_all(sanitized):
            if doc and isinstance(doc, dict):
                docs.append(doc)
    except yaml.YAMLError as e:
        print(f"ERROR: Failed to parse {filepath}: {e}", file=sys.stderr)
        return []

    # Re-parse with original content for content-level checks
    # We use the sanitized parse for structure but check original systemMessage
    original_docs = []
    try:
        # Also try parsing original — if it works, prefer it
        for doc in yaml.safe_load_all(raw.replace("'{{ .Release.Namespace }}'", "'genai'")):
            if doc and isinstance(doc, dict):
                original_docs.append(doc)
    except yaml.YAMLError:
        # Fall back to sanitized version
        original_docs = docs

    return original_docs if len(original_docs) == len(docs) else docs


def find_agent_crds(docs: list[dict]) -> list[dict]:
    """Filter documents to only Agent CRDs."""
    agents = []
    for doc in docs:
        kind = doc.get("kind", "")
        api = doc.get("apiVersion", "")
        # Accept any kagent.dev apiVersion with kind Agent
        if kind == "Agent" and "kagent.dev" in str(api):
            agents.append(doc)
    return agents


# ── Main ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Lint kagent Agent CRDs")
    parser.add_argument(
        "--file", "-f",
        help="Lint a single YAML file instead of scanning templates directory",
    )
    parser.add_argument(
        "--dir", "-d",
        help=f"Templates directory to scan (default: {DEFAULT_TEMPLATES_DIR})",
        default=DEFAULT_TEMPLATES_DIR,
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on ANY warning (for CI)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output JSON report",
    )
    args = parser.parse_args()

    # Find repo root
    repo_root = os.environ.get("REPO_ROOT")
    if not repo_root:
        # Walk up from script location or cwd
        candidate = Path(__file__).resolve().parent.parent
        if (candidate / "charts").is_dir():
            repo_root = str(candidate)
        elif (Path.cwd() / "charts").is_dir():
            repo_root = str(Path.cwd())
        else:
            repo_root = str(Path.cwd())

    # Collect files to lint
    files_to_lint: list[str] = []
    if args.file:
        p = Path(args.file)
        if not p.is_absolute():
            p = Path(repo_root) / p
        files_to_lint.append(str(p))
    else:
        templates_dir = Path(repo_root) / args.dir
        if not templates_dir.is_dir():
            if not args.json_output:
                print(f"ERROR: Templates directory not found: {templates_dir}", file=sys.stderr)
            sys.exit(2)
        for f in sorted(templates_dir.glob("*.yaml")):
            files_to_lint.append(str(f))
        for f in sorted(templates_dir.glob("*.yml")):
            files_to_lint.append(str(f))

    # Lint all Agent CRDs
    all_reports: list[AgentReport] = []
    total_agents = 0
    total_errors = 0
    total_warnings = 0
    files_scanned = 0

    for filepath in files_to_lint:
        files_scanned += 1
        docs = parse_yaml_file(filepath)
        agents = find_agent_crds(docs)

        rel_path = os.path.relpath(filepath, repo_root)

        for agent_doc in agents:
            total_agents += 1
            report = lint_agent(agent_doc, rel_path)
            all_reports.append(report)

            errors = [m for m in report.messages if m.level == "error"]
            warnings = [m for m in report.messages if m.level == "warning"]
            total_errors += len(errors)
            total_warnings += len(warnings)

    # Output
    if args.json_output:
        result = {
            "files_scanned": files_scanned,
            "agents_found": total_agents,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "passed": total_errors == 0 and (not args.strict or total_warnings == 0),
            "agents": [r.to_dict() for r in all_reports],
        }
        print(json.dumps(result, indent=2))
    else:
        # Human-readable output
        if total_agents == 0:
            print(f"Scanned {files_scanned} file(s) — no Agent CRDs found.")
        else:
            print(f"Scanned {files_scanned} file(s), found {total_agents} Agent CRD(s)\n")

            for report in all_reports:
                errors = [m for m in report.messages if m.level == "error"]
                warnings = [m for m in report.messages if m.level == "warning"]

                if not errors and not warnings:
                    status = "\u2713"
                elif not errors:
                    status = "\u2713" if not args.strict else "\u2717"
                else:
                    status = "\u2717"

                print(f"  {status} {report.name} ({report.file})")
                for m in report.messages:
                    icon = "\u2717" if m.level == "error" else "\u26a0"
                    print(f"    {icon} [{m.level}] {m.message}")

            print()
            print(f"Results: {total_errors} error(s), {total_warnings} warning(s)")

            if total_errors == 0 and total_warnings == 0:
                print("All checks passed.")
            elif total_errors == 0:
                print("No errors. Warnings present" + (" (--strict treats as failure)." if args.strict else "."))

    # Exit code
    if total_errors > 0:
        sys.exit(1)
    if args.strict and total_warnings > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
