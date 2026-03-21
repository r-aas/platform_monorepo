# /// script
# requires-python = ">=3.12"
# dependencies = ["openai", "pyyaml"]
# ///
"""Skill optimization test harness.

Runs a skill against eval scenarios, judges outputs with an LLM,
and reports pass rates. Part of the autoresearch-inspired skill
optimization system adapted from Karpathy's methodology.

Usage:
    uv run scripts/skill-optimize.py --skill-name fastapi-templates --verbose
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from openai import OpenAI

SKILLS_DIR = Path.home() / ".claude" / "skills"


@dataclass
class EvalConfig:
    name: str
    runs_per_iteration: int
    pass_threshold: float
    scenarios: list[dict[str, str]]
    criteria: list[dict[str, str]]


@dataclass
class JudgmentResult:
    scenario: str
    run: int
    criterion_id: str
    passed: bool
    raw_response: str


@dataclass
class EvalResult:
    score: int
    max_score: int
    pass_rate: float
    failures: list[dict[str, str]]
    details: list[JudgmentResult] = field(default_factory=list)


def load_evals(skill_name: str) -> EvalConfig:
    """Load evals.yml from the skill directory."""
    evals_path = SKILLS_DIR / skill_name / "evals.yml"
    if not evals_path.exists():
        print(f"Error: {evals_path} not found.", file=sys.stderr)
        print(
            f"Create evals.yml in ~/.claude/skills/{skill_name}/ or use "
            "/skill-optimize to generate one.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(evals_path) as f:
        data = yaml.safe_load(f)

    required_keys = {"name", "scenarios", "criteria"}
    missing = required_keys - set(data.keys())
    if missing:
        print(f"Error: evals.yml missing required keys: {missing}", file=sys.stderr)
        sys.exit(1)

    if not data["scenarios"]:
        print("Error: evals.yml has no scenarios.", file=sys.stderr)
        sys.exit(1)

    if not data["criteria"]:
        print("Error: evals.yml has no criteria.", file=sys.stderr)
        sys.exit(1)

    return EvalConfig(
        name=data["name"],
        runs_per_iteration=data.get("runs_per_iteration", 3),
        pass_threshold=data.get("pass_threshold", 0.85),
        scenarios=data["scenarios"],
        criteria=data["criteria"],
    )


def invoke_skill(prompt: str, verbose: bool = False) -> str | None:
    """Invoke claude CLI with a prompt and capture output."""
    cmd = [
        "claude",
        "-p",
        prompt,
        "--allowedTools",
        "Read,Write,Edit,Bash,Glob,Grep",
        "--output-format",
        "json",
    ]

    if verbose:
        print(f"  Running: claude -p \"{prompt[:80]}...\"", file=sys.stderr)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout per invocation
        )
        if result.returncode != 0:
            if verbose:
                print(f"  claude CLI failed (exit {result.returncode}): {result.stderr[:200]}", file=sys.stderr)
            return None

        # Parse JSON output to extract the result text
        try:
            output_data = json.loads(result.stdout)
            # claude --output-format json returns {"result": "...", ...}
            if isinstance(output_data, dict):
                return output_data.get("result", result.stdout)
            return result.stdout
        except json.JSONDecodeError:
            return result.stdout

    except subprocess.TimeoutExpired:
        if verbose:
            print("  claude CLI timed out after 300s", file=sys.stderr)
        return None
    except FileNotFoundError:
        print("Error: 'claude' CLI not found. Is it installed and on PATH?", file=sys.stderr)
        sys.exit(1)


def judge_output(
    client: OpenAI,
    model: str,
    criterion_question: str,
    output: str,
    verbose: bool = False,
) -> tuple[bool, str]:
    """Ask the judge model a binary yes/no question about the output."""
    judge_prompt = (
        f"Answer YES or NO only. {criterion_question}\n\n"
        f"Output to evaluate:\n{output}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": judge_prompt}],
            max_tokens=10,
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        passed = raw.upper().startswith("YES")

        if verbose:
            print(f"    Judge: {criterion_question[:60]}... -> {raw}", file=sys.stderr)

        return passed, raw

    except Exception as e:
        if verbose:
            print(f"    Judge error: {e}", file=sys.stderr)
        return False, f"ERROR: {e}"


def append_results_tsv(
    skill_name: str,
    iteration: int,
    pass_rate: float,
    score: int,
    max_score: int,
    status: str,
    description: str,
) -> None:
    """Append a row to results.tsv in the skill directory."""
    results_path = SKILLS_DIR / skill_name / "results.tsv"
    write_header = not results_path.exists()

    with open(results_path, "a") as f:
        if write_header:
            f.write("iteration\tpass_rate\tscore\tmax_score\tstatus\tdescription\n")
        f.write(f"{iteration}\t{pass_rate:.3f}\t{score}\t{max_score}\t{status}\t{description}\n")


def get_next_iteration(skill_name: str) -> int:
    """Determine the next iteration number from results.tsv."""
    results_path = SKILLS_DIR / skill_name / "results.tsv"
    if not results_path.exists():
        return 0

    lines = results_path.read_text().strip().split("\n")
    if len(lines) <= 1:  # header only
        return 0

    try:
        last_iter = int(lines[-1].split("\t")[0])
        return last_iter + 1
    except (ValueError, IndexError):
        return 0


def run_evaluation(
    config: EvalConfig,
    client: OpenAI,
    judge_model: str,
    verbose: bool = False,
) -> EvalResult:
    """Run all scenarios and judge all outputs against all criteria."""
    all_judgments: list[JudgmentResult] = []
    failures: list[dict[str, str]] = []

    total_scenarios = len(config.scenarios)
    total_runs = config.runs_per_iteration

    for s_idx, scenario in enumerate(config.scenarios):
        scenario_name = scenario["name"]
        prompt = scenario["prompt"]

        if verbose:
            print(
                f"\nScenario [{s_idx + 1}/{total_scenarios}]: {scenario_name}",
                file=sys.stderr,
            )

        for run in range(total_runs):
            if verbose:
                print(f"  Run {run + 1}/{total_runs}", file=sys.stderr)

            output = invoke_skill(prompt, verbose=verbose)

            if output is None:
                # All criteria fail if skill invocation failed
                for criterion in config.criteria:
                    judgment = JudgmentResult(
                        scenario=scenario_name,
                        run=run + 1,
                        criterion_id=criterion["id"],
                        passed=False,
                        raw_response="SKILL_INVOCATION_FAILED",
                    )
                    all_judgments.append(judgment)
                    failures.append({
                        "scenario": scenario_name,
                        "run": run + 1,
                        "criterion": criterion["id"],
                        "reason": "Skill invocation failed",
                    })
                continue

            # Judge each criterion
            for criterion in config.criteria:
                passed, raw = judge_output(
                    client, judge_model, criterion["question"], output, verbose=verbose
                )
                judgment = JudgmentResult(
                    scenario=scenario_name,
                    run=run + 1,
                    criterion_id=criterion["id"],
                    passed=passed,
                    raw_response=raw,
                )
                all_judgments.append(judgment)

                if not passed:
                    failures.append({
                        "scenario": scenario_name,
                        "run": run + 1,
                        "criterion": criterion["id"],
                        "reason": raw,
                    })

    score = sum(1 for j in all_judgments if j.passed)
    max_score = len(config.scenarios) * config.runs_per_iteration * len(config.criteria)
    pass_rate = score / max_score if max_score > 0 else 0.0

    return EvalResult(
        score=score,
        max_score=max_score,
        pass_rate=pass_rate,
        failures=failures,
        details=all_judgments,
    )


def resolve_judge_model(model_alias: str) -> str:
    """Resolve a model alias to a model name available on the judge endpoint."""
    aliases = {
        "haiku": "claude-3-haiku",
        "sonnet": "claude-3-sonnet",
        "qwen": "qwen2.5:14b",
        "llama": "llama3.1:8b",
    }
    return aliases.get(model_alias, model_alias)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Skill optimization test harness — evaluate a Claude Code skill against binary criteria."
    )
    parser.add_argument(
        "--skill-name",
        required=True,
        help="Name of the skill directory under ~/.claude/skills/",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="Maximum optimization iterations (default: 10). "
        "This script runs a single evaluation pass; the /skill-optimize command handles the loop.",
    )
    parser.add_argument(
        "--judge-model",
        default="haiku",
        help="Model to use for judging (default: haiku). "
        "Can be an alias (haiku, sonnet, qwen, llama) or a full model name.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress to stderr.",
    )
    args = parser.parse_args()

    # Validate skill exists
    skill_dir = SKILLS_DIR / args.skill_name
    if not skill_dir.exists():
        print(f"Error: Skill directory not found: {skill_dir}", file=sys.stderr)
        sys.exit(1)

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        print(f"Error: SKILL.md not found in {skill_dir}", file=sys.stderr)
        sys.exit(1)

    # Load eval config
    config = load_evals(args.skill_name)

    if args.verbose:
        print(f"Skill: {args.skill_name}", file=sys.stderr)
        print(f"Scenarios: {len(config.scenarios)}", file=sys.stderr)
        print(f"Criteria: {len(config.criteria)}", file=sys.stderr)
        print(f"Runs/iteration: {config.runs_per_iteration}", file=sys.stderr)
        print(
            f"Max score: {len(config.scenarios) * config.runs_per_iteration * len(config.criteria)}",
            file=sys.stderr,
        )

    # Set up judge client
    judge_base_url = os.environ.get("JUDGE_BASE_URL", "http://localhost:11434/v1")
    judge_api_key = os.environ.get("JUDGE_API_KEY", "ollama")
    judge_model = resolve_judge_model(args.judge_model)

    client = OpenAI(base_url=judge_base_url, api_key=judge_api_key)

    if args.verbose:
        print(f"Judge: {judge_model} @ {judge_base_url}", file=sys.stderr)

    # Run evaluation
    start_time = time.time()
    result = run_evaluation(config, client, judge_model, verbose=args.verbose)
    elapsed = time.time() - start_time

    if args.verbose:
        print(f"\nCompleted in {elapsed:.1f}s", file=sys.stderr)
        print(f"Score: {result.score}/{result.max_score} ({result.pass_rate:.1%})", file=sys.stderr)

    # Append to results.tsv
    iteration = get_next_iteration(args.skill_name)
    append_results_tsv(
        skill_name=args.skill_name,
        iteration=iteration,
        pass_rate=result.pass_rate,
        score=result.score,
        max_score=result.max_score,
        status="eval",
        description=f"automated eval run ({elapsed:.0f}s)",
    )

    # Output JSON to stdout
    output = {
        "skill": args.skill_name,
        "iteration": iteration,
        "score": result.score,
        "max_score": result.max_score,
        "pass_rate": round(result.pass_rate, 4),
        "pass_threshold": config.pass_threshold,
        "elapsed_seconds": round(elapsed, 1),
        "failures": result.failures,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
