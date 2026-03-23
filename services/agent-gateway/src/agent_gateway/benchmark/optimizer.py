"""Auto-prompt optimizer — score, gap-analyze, and improve skill prompt_fragments [D.07]."""

from __future__ import annotations

from pathlib import Path

import yaml
from mlflow import MlflowClient

from agent_gateway.benchmark.runner import load_dataset


def score_prompt_coverage(prompt_fragment: str, cases: list[dict]) -> float:
    """Score prompt coverage: fraction of expected output terms present in prompt.

    Returns 0.0–1.0.  Empty cases → 1.0 (nothing to miss).
    """
    if not cases:
        return 1.0

    prompt_lower = prompt_fragment.lower()
    hits = 0
    total = 0
    for case in cases:
        for term in case.get("expected_output_contains", []):
            total += 1
            if term.lower() in prompt_lower:
                hits += 1

    return hits / total if total > 0 else 1.0


def extract_uncovered_terms(prompt_fragment: str, cases: list[dict]) -> list[str]:
    """Return expected output terms from eval cases NOT mentioned in prompt_fragment.

    Preserves insertion order; deduplicates.
    """
    prompt_lower = prompt_fragment.lower()
    seen: set[str] = set()
    uncovered: list[str] = []

    for case in cases:
        for term in case.get("expected_output_contains", []):
            if term.lower() not in prompt_lower and term not in seen:
                uncovered.append(term)
                seen.add(term)

    return uncovered


def suggest_prompt_improvements(prompt_fragment: str, uncovered_terms: list[str]) -> str:
    """Append coverage bullets for uncovered terms to prompt_fragment.

    Returns unchanged prompt if no uncovered terms.  Caps additions at 5 terms.
    """
    if not uncovered_terms:
        return prompt_fragment

    additions = "\n".join(
        f"  - When relevant, include information about: {term}"
        for term in uncovered_terms[:5]
    )
    return prompt_fragment.rstrip() + "\n" + additions + "\n"


def optimize_skill_prompt(skill_yaml_path: Path, datasets_root: Path) -> dict:
    """Run one optimization cycle on a skill.

    Steps:
    1. Load skill YAML + all referenced eval datasets
    2. Score current prompt_fragment coverage
    3. Extract uncovered terms
    4. Generate improved prompt_fragment
    5. Re-score to measure improvement

    Returns a result dict with before/after scores.  Pure: no file writes.
    """
    data = yaml.safe_load(skill_yaml_path.read_text())
    skill_name: str = data.get("name", skill_yaml_path.stem)
    prompt_fragment: str = data.get("prompt_fragment", "")

    all_cases: list[dict] = []
    for task in data.get("tasks", []):
        dataset_rel = task.get("evaluation", {}).get("dataset") if task.get("evaluation") else None
        if dataset_rel:
            full_path = datasets_root / dataset_rel
            if full_path.exists():
                ds = load_dataset(full_path)
                all_cases.extend(ds.get("cases", []))

    before_score = score_prompt_coverage(prompt_fragment, all_cases)
    uncovered = extract_uncovered_terms(prompt_fragment, all_cases)
    improved = suggest_prompt_improvements(prompt_fragment, uncovered)
    after_score = score_prompt_coverage(improved, all_cases)

    return {
        "skill": skill_name,
        "before_score": before_score,
        "after_score": after_score,
        "uncovered_terms": uncovered[:10],
        "improved_prompt": improved,
        "improvement": after_score - before_score,
    }


def record_optimization_result(optimization: dict, tracking_uri: str) -> str:
    """Log a prompt optimization result to MLflow.  Returns run_id."""
    client = MlflowClient(tracking_uri=tracking_uri)
    skill = optimization["skill"]
    experiment_name = f"prompt-opt:{skill}"

    try:
        experiment_id = client.create_experiment(experiment_name)
    except Exception:
        exp = client.get_experiment_by_name(experiment_name)
        experiment_id = exp.experiment_id if exp else "0"

    run = client.create_run(experiment_id=experiment_id)
    run_id = run.info.run_id

    client.log_metric(run_id, "before_score", optimization["before_score"])
    client.log_metric(run_id, "after_score", optimization["after_score"])
    client.log_metric(run_id, "improvement", optimization["improvement"])
    client.log_param(run_id, "skill", skill)
    client.log_param(run_id, "uncovered_count", len(optimization.get("uncovered_terms", [])))
    client.log_text(run_id, optimization.get("improved_prompt", ""), "improved_prompt.txt")
    client.set_terminated(run_id, status="FINISHED")

    return run_id
