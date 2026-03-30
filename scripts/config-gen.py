#!/usr/bin/env python3
"""Generate .env.generated and litellm/config.yaml from config.yaml.

Usage:
    python scripts/config-gen.py              # generate all outputs
    python scripts/config-gen.py --validate   # validate only (exit 0/1)
    python scripts/config-gen.py --diff       # show what would change
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"
ENV_OUTPUT = REPO_ROOT / ".env.generated"
LITELLM_OUTPUT = REPO_ROOT / "litellm" / "config.yaml"

HEADER = "# AUTO-GENERATED from config.yaml — do not edit directly.\n# Run: task config\n"


# ── Load ──────────────────────────────────────────────────────────────────────


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


# ── Validate ──────────────────────────────────────────────────────────────────


def validate(config: dict) -> list[str]:
    errors: list[str] = []
    services = config.get("services", {})
    inference = config.get("inference", {})

    # Required fields
    for name, svc in services.items():
        if "port" in svc and "health" not in svc:
            errors.append(f"Service '{name}' has port but no health endpoint")

    # Port conflicts
    ports: dict[int, str] = {}
    for name, svc in services.items():
        port = svc.get("port")
        if port is not None:
            if port in ports:
                errors.append(
                    f"Port conflict: {name} and {ports[port]} both use port {port}"
                )
            ports[port] = name

    # Model consistency
    model_names = {m["name"] for m in inference.get("models", [])}
    default = inference.get("default_model", "")
    if default and default not in model_names:
        errors.append(
            f"default_model '{default}' not found in inference.models"
        )

    # Schema checks
    if "stack" not in config:
        errors.append("Missing top-level 'stack' section")
    if "inference" not in config:
        errors.append("Missing top-level 'inference' section")

    return errors


# ── Generate .env ─────────────────────────────────────────────────────────────


def generate_env(config: dict) -> str:
    svc = config["services"]
    inf = config["inference"]
    lines: list[str] = [HEADER]

    def section(title: str):
        lines.append(f"\n# ── {title} " + "─" * max(1, 50 - len(title)))

    def kv(key: str, val):
        lines.append(f"{key}={val}")

    # ── Stack
    section("Stack")
    kv("TIMEZONE", config["stack"]["timezone"])

    # ── n8n
    section("n8n")
    kv("N8N_VERSION", svc["n8n"]["version"])
    kv("N8N_PORT", svc["n8n"]["port"])

    section("n8n Postgres")
    pg = svc["n8n"]["postgres"]
    kv("N8N_POSTGRES_VERSION", pg["version"])
    kv("N8N_POSTGRES_USER", pg["user"])
    kv("N8N_POSTGRES_DB", pg["db"])

    # ── pgvector
    section("pgvector")
    kv("PGVECTOR_VERSION", svc["pgvector"]["version"])
    kv("PGVECTOR_USER", svc["pgvector"]["user"])
    kv("PGVECTOR_DB", svc["pgvector"]["db"])

    # ── MLflow
    section("MLflow")
    kv("MLFLOW_VERSION", svc["mlflow"]["version"])
    kv("MLFLOW_PORT", svc["mlflow"]["port"])
    kv("MLFLOW_TRACKING_URI", f"http://mlflow:{svc['mlflow']['port']}")

    section("MLflow Postgres")
    pg = svc["mlflow"]["postgres"]
    kv("MLFLOW_POSTGRES_VERSION", pg["version"])
    kv("MLFLOW_POSTGRES_USER", pg["user"])
    kv("MLFLOW_POSTGRES_DB", pg["db"])

    # ── MinIO
    section("MinIO")
    kv("MINIO_VERSION", svc["minio"]["version"])
    kv("MINIO_MC_VERSION", svc["minio"]["mc_version"])
    kv("MINIO_ROOT_USER", svc["minio"]["root_user"])
    kv("MINIO_PORT", svc["minio"]["port"])
    kv("MINIO_BUCKET", svc["minio"]["bucket"])
    kv("AWS_DEFAULT_REGION", svc["minio"]["region"])

    # ── LiteLLM
    section("LiteLLM Proxy")
    kv("LITELLM_VERSION", svc["litellm"]["version"])
    kv("LITELLM_PORT", svc["litellm"]["port"])

    # ── Streaming Proxy
    section("Streaming Proxy")
    kv("STREAMING_PROXY_PORT", svc["streaming_proxy"]["port"])

    # ── Langfuse
    section("Langfuse")
    kv("LANGFUSE_VERSION", svc["langfuse"]["version"])
    kv("LANGFUSE_PORT", svc["langfuse"]["port"])
    pg = svc["langfuse"]["postgres"]
    kv("LANGFUSE_POSTGRES_VERSION", pg["version"])
    kv("LANGFUSE_POSTGRES_USER", pg["user"])
    kv("LANGFUSE_POSTGRES_DB", pg["db"])
    kv("LANGFUSE_PUBLIC_KEY", svc["langfuse"]["public_key"])
    kv("LANGFUSE_SECRET_KEY", svc["langfuse"]["secret_key"])

    # ── Inference
    section("Inference Provider")
    litellm_port = svc["litellm"]["port"]
    kv("INFERENCE_BASE_URL", f"http://litellm:{litellm_port}/v1")
    kv("INFERENCE_DEFAULT_MODEL", inf["default_model"])
    model_list = ",".join(m["name"] for m in inf["models"])
    kv("INFERENCE_ALLOWED_MODELS", model_list)

    # ── MCP Gateway
    section("MCP Gateway")
    kv("MCP_GATEWAY_PORT", svc["mcp_gateway"]["port"])
    kv("MCP_GATEWAY_SERVERS", svc["mcp_gateway"]["servers"])

    # ── Session
    section("Session Management")
    kv("SESSION_MAX_MESSAGES", config["session"]["max_messages"])

    # ── Drift
    section("Drift Monitor Thresholds")
    drift = config["drift"]
    kv("DRIFT_LATENCY_MAX_MS", drift["latency_max_ms"])
    kv("DRIFT_ERROR_RATE_MAX", drift["error_rate_max"])
    kv("DRIFT_TOKEN_BUDGET_DAILY", drift["token_budget_daily"])

    # ── Webhook
    section("Webhook Security")
    kv("WEBHOOK_API_KEY", config["webhook"]["api_key"])

    # ── OpenAI SDK
    section("OpenAI SDK (host-side)")
    sdk = config["openai_sdk"]
    kv("OPENAI_BASE_URL", sdk["base_url"])
    kv("OPENAI_API_KEY", sdk["api_key"])
    kv("OPENAI_MODEL", sdk["model"])

    lines.append("")
    return "\n".join(lines)


# ── Generate LiteLLM config ──────────────────────────────────────────────────


def generate_litellm(config: dict) -> str:
    inf = config["inference"]
    settings = config["services"]["litellm"].get("settings", {})
    api_base = f"http://{inf['ollama_host']}"

    model_list = []
    for m in inf["models"]:
        model_list.append({
            "model_name": m["name"],
            "litellm_params": {
                "model": f"ollama/{m['name']}",
                "api_base": api_base,
            },
        })

    litellm_settings = {}
    if "callbacks" in settings:
        litellm_settings["success_callback"] = settings["callbacks"]
    if "drop_params" in settings:
        litellm_settings["drop_params"] = settings["drop_params"]
    if "request_timeout" in settings:
        litellm_settings["request_timeout"] = settings["request_timeout"]

    general_settings = {
        "master_key": "os.environ/LITELLM_MASTER_KEY",
    }

    doc = {
        "model_list": model_list,
        "litellm_settings": litellm_settings,
        "general_settings": general_settings,
    }

    output = HEADER + "\n"
    output += yaml.dump(doc, default_flow_style=False, sort_keys=False)
    return output


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Generate config from config.yaml")
    parser.add_argument("--validate", action="store_true", help="Validate only (exit 0/1)")
    parser.add_argument("--diff", action="store_true", help="Show diff without writing")
    args = parser.parse_args()

    if not CONFIG_PATH.exists():
        print(f"ERROR: {CONFIG_PATH} not found", file=sys.stderr)
        sys.exit(1)

    config = load_config(CONFIG_PATH)

    # Validate
    errors = validate(config)
    if errors:
        print("Validation errors:", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        sys.exit(1)
    print("✓ config.yaml is valid")

    if args.validate:
        return

    # Generate
    env_content = generate_env(config)
    litellm_content = generate_litellm(config)

    if args.diff:
        import difflib

        if ENV_OUTPUT.exists():
            old = ENV_OUTPUT.read_text().splitlines(keepends=True)
            new = env_content.splitlines(keepends=True)
            diff = difflib.unified_diff(old, new, fromfile=str(ENV_OUTPUT), tofile="(generated)")
            sys.stdout.writelines(diff)
        else:
            print(f"(new file) {ENV_OUTPUT}")

        if LITELLM_OUTPUT.exists():
            old = LITELLM_OUTPUT.read_text().splitlines(keepends=True)
            new = litellm_content.splitlines(keepends=True)
            diff = difflib.unified_diff(old, new, fromfile=str(LITELLM_OUTPUT), tofile="(generated)")
            sys.stdout.writelines(diff)
        else:
            print(f"(new file) {LITELLM_OUTPUT}")
        return

    # Write
    ENV_OUTPUT.write_text(env_content)
    print(f"✓ {ENV_OUTPUT.relative_to(REPO_ROOT)}")

    LITELLM_OUTPUT.write_text(litellm_content)
    print(f"✓ {LITELLM_OUTPUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
