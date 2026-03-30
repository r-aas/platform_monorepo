#!/usr/bin/env python3
"""Optimize a prompt using MLflow GEPA algorithm.

Loads a prompt from the MLflow registry, runs iterative optimization with
training data, and registers the improved version under a staging alias.

Usage:
    uv run python scripts/optimize_prompt.py summarizer
    uv run python scripts/optimize_prompt.py summarizer --model qwen3:32b
    uv run python scripts/optimize_prompt.py summarizer --alias staging --max-calls 200
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from mlflow.genai.optimize import GepaPromptOptimizer
from mlflow.genai.scorers import scorer
from openai import OpenAI

import mlflow

# ── Configuration ─────────────────────────────────────────────────────────────

TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5050")
BASE_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
API_KEY = os.getenv("OPENAI_API_KEY", "ollama")
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "qwen2.5:14b")
TRAINING_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "training")


# ── Helpers ───────────────────────────────────────────────────────────────────


def load_training_data(prompt_name: str) -> list[dict]:
    """Load training data from data/training/{prompt_name}.jsonl."""
    path = os.path.join(TRAINING_DIR, f"{prompt_name}.jsonl")
    if not os.path.exists(path):
        print(f"Error: training data not found at {path}", file=sys.stderr)
        print(
            f"Create {path} with one JSON object per line:\n"
            '  {"inputs": {"var1": "...", "var2": "..."}, "expectations": {"expected_response": "..."}}'
        )
        sys.exit(1)

    data = []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                data.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"Error: invalid JSON on line {i} of {path}: {e}", file=sys.stderr)
                sys.exit(1)

    if not data:
        print(f"Error: no training examples found in {path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(data)} training examples from {path}")
    return data


def extract_variables(template: str) -> list[str]:
    """Extract {{ var }} names from a template."""
    return list({m.strip() for m in re.findall(r"\{\{\s*(\w+)\s*\}\}", template)})


def register_optimized(
    prompt_name: str,
    new_template: str,
    alias: str,
    original_version: str,
) -> str:
    """Register the optimized prompt as a new version and set alias."""
    import requests

    mlflow_url = TRACKING_URI + "/api/2.0/mlflow"

    # Create new version
    resp = requests.post(
        f"{mlflow_url}/model-versions/create",
        json={"name": prompt_name, "source": f"prompts:/{prompt_name}"},
    )
    resp.raise_for_status()
    version = resp.json()["model_version"]["version"]

    # Set template tag
    requests.post(
        f"{mlflow_url}/model-versions/set-tag",
        json={
            "name": prompt_name,
            "version": version,
            "key": "mlflow.prompt.text",
            "value": new_template,
        },
    ).raise_for_status()

    # Set commit message
    requests.post(
        f"{mlflow_url}/model-versions/set-tag",
        json={
            "name": prompt_name,
            "version": version,
            "key": "mlflow.prompt.commit_message",
            "value": f"GEPA-optimized from v{original_version}",
        },
    ).raise_for_status()

    # Set alias
    requests.post(
        f"{mlflow_url}/registered-models/alias",
        json={"name": prompt_name, "alias": alias, "version": version},
    ).raise_for_status()

    return version


# ── Scorers ───────────────────────────────────────────────────────────────────


@scorer
def quality_scorer(outputs, expectations: dict) -> float:
    """Generic quality scorer: exact match = 1.0, partial match by word overlap."""
    if not expectations or "expected_response" not in expectations:
        # No expectation — score based on non-empty response
        return 1.0 if outputs and len(str(outputs).strip()) > 0 else 0.0

    expected = str(expectations["expected_response"]).lower().strip()
    actual = str(outputs).lower().strip()

    # Exact match
    if actual == expected:
        return 1.0

    # Word overlap ratio
    expected_words = set(expected.split())
    actual_words = set(actual.split())
    if not expected_words:
        return 1.0
    overlap = len(expected_words & actual_words) / len(expected_words)
    return round(min(overlap, 1.0), 3)


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimize a prompt with MLflow GEPA")
    parser.add_argument("prompt_name", help="Name of the prompt in MLflow registry")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"LLM model (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--alias", default="staging", help="Alias for optimized version (default: staging)"
    )
    parser.add_argument(
        "--max-calls", type=int, default=100, help="Max metric evaluation calls (default: 100)"
    )
    parser.add_argument(
        "--source-alias",
        default="production",
        help="Source alias to optimize from (default: production)",
    )
    args = parser.parse_args()

    mlflow.set_tracking_uri(TRACKING_URI)
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

    print("══ MLflow Prompt Optimization (GEPA) ══")
    print(f"Prompt:     {args.prompt_name}")
    print(f"Model:      {args.model}")
    print(f"MLflow:     {TRACKING_URI}")
    print(f"Inference:  {BASE_URL}")
    print()

    # 1. Load current prompt from registry
    prompt_uri = f"prompts:/{args.prompt_name}@{args.source_alias}"
    try:
        prompt = mlflow.genai.load_prompt(prompt_uri)
    except Exception as e:
        print(
            f"Error loading prompt '{args.prompt_name}' (alias: {args.source_alias}): {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    original_template = prompt.template
    original_version = prompt.version
    variables = extract_variables(original_template)

    print(f"Loaded: v{original_version} ({args.source_alias})")
    print(f"Variables: {variables}")
    print("Template preview:")
    for line in original_template.split("\n")[:5]:
        print(f"  │ {line}")
    if original_template.count("\n") > 4:
        print(f"  │ ... ({original_template.count(chr(10)) + 1} lines total)")
    print()

    # 2. Load training data
    train_data = load_training_data(args.prompt_name)

    # Validate training data has the right variables
    if train_data:
        sample_inputs = train_data[0].get("inputs", {})
        missing = [v for v in variables if v not in sample_inputs]
        extra = [v for v in sample_inputs if v not in variables]
        if missing:
            print(f"⚠ Training data missing variables: {missing}")
        if extra:
            print(f"⚠ Training data has extra variables: {extra}")
    print()

    # 3. Define predict function
    def predict_fn(**kwargs):
        loaded = mlflow.genai.load_prompt(prompt_uri)
        rendered = loaded.format(**kwargs)
        response = client.chat.completions.create(
            model=args.model,
            messages=[{"role": "user", "content": rendered}],
            temperature=0.7,
        )
        return response.choices[0].message.content

    # 4. Run optimization
    print("Starting GEPA optimization...")
    print(f"  max_metric_calls: {args.max_calls}")
    print(f"  reflection_model: openai:/{args.model}")
    print()

    try:
        result = mlflow.genai.optimize_prompts(
            predict_fn=predict_fn,
            train_data=train_data,
            prompt_uris=[prompt_uri],
            optimizer=GepaPromptOptimizer(
                reflection_model=f"openai:/{args.model}",
                max_metric_calls=args.max_calls,
            ),
            scorers=[quality_scorer],
            enable_tracking=True,
        )
    except Exception as e:
        print(f"\nOptimization failed: {e}", file=sys.stderr)
        sys.exit(1)

    # 5. Extract result
    if not result.optimized_prompts:
        print("No optimized prompts returned — the original may already be optimal.")
        sys.exit(0)

    optimized = result.optimized_prompts[0]
    new_template = optimized.template

    print()
    print("══ Optimization Complete ══")
    print(f"Initial score: {result.initial_eval_score:.3f}")
    print(f"Final score:   {result.final_eval_score:.3f}")
    delta = result.final_eval_score - result.initial_eval_score
    print(
        f"Improvement:   {delta:+.3f} ({delta / max(result.initial_eval_score, 0.001) * 100:+.1f}%)"
    )
    print()

    # 6. Show diff
    print("── Original Template ──")
    for line in original_template.split("\n"):
        print(f"  - {line}")
    print()
    print("── Optimized Template ──")
    for line in new_template.split("\n"):
        print(f"  + {line}")
    print()

    if new_template.strip() == original_template.strip():
        print("Templates are identical — no changes needed.")
        sys.exit(0)

    # 7. Register optimized version
    new_version = register_optimized(
        prompt_name=args.prompt_name,
        new_template=new_template,
        alias=args.alias,
        original_version=original_version,
    )

    print(f"✓ Registered as v{new_version} (alias: {args.alias})")
    print()
    print("Next steps:")
    print("  1. Review the optimized template above")
    print("  2. Run benchmarks:  task benchmark")
    print("  3. If happy, promote:  curl -s localhost:5678/webhook/prompts \\")
    print(
        f'       -d \'{{"action":"promote","name":"{args.prompt_name}","version":{new_version}}}\''
    )


if __name__ == "__main__":
    main()
