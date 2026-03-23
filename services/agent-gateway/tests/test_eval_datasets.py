"""Validate eval dataset quality: 10+ cases, required fields, proper structure."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

MONOREPO = Path(__file__).parents[3]
EVAL_ROOT = MONOREPO / "skills" / "eval"

REQUIRED_FIELDS = {"id", "input", "expected_output_contains"}

EXPECTED_DATASETS = [
    # (skill, task, min_cases)
    ("kubernetes-ops", "deploy-model", 10),
    ("kubernetes-ops", "check-status", 10),
    ("mlflow-tracking", "log-metrics", 10),
    ("mlflow-tracking", "search-experiments", 10),
    ("n8n-workflow-ops", "list-workflows", 10),
]


def load_dataset(skill: str, task: str) -> dict:
    path = EVAL_ROOT / skill / f"{task}.json"
    assert path.exists(), f"Dataset not found: {path}"
    return json.loads(path.read_text())


@pytest.mark.parametrize("skill,task,min_cases", EXPECTED_DATASETS)
def test_dataset_exists(skill: str, task: str, min_cases: int):
    """Every expected dataset file exists and loads as valid JSON."""
    data = load_dataset(skill, task)
    assert data["skill"] == skill
    assert data["task"] == task


@pytest.mark.parametrize("skill,task,min_cases", EXPECTED_DATASETS)
def test_dataset_has_minimum_cases(skill: str, task: str, min_cases: int):
    """Each dataset has at least min_cases cases (D.06 requirement: 10+)."""
    data = load_dataset(skill, task)
    cases = data.get("cases", [])
    assert len(cases) >= min_cases, (
        f"{skill}/{task} has {len(cases)} cases, expected >= {min_cases}"
    )


@pytest.mark.parametrize("skill,task,min_cases", EXPECTED_DATASETS)
def test_dataset_case_required_fields(skill: str, task: str, min_cases: int):
    """Every case has id, input, and expected_output_contains fields."""
    data = load_dataset(skill, task)
    for case in data["cases"]:
        missing = REQUIRED_FIELDS - set(case.keys())
        assert not missing, f"Case {case.get('id', '?')} in {skill}/{task} missing: {missing}"


@pytest.mark.parametrize("skill,task,min_cases", EXPECTED_DATASETS)
def test_dataset_case_ids_unique(skill: str, task: str, min_cases: int):
    """Case IDs are unique within each dataset."""
    data = load_dataset(skill, task)
    ids = [c["id"] for c in data["cases"]]
    assert len(ids) == len(set(ids)), f"Duplicate IDs in {skill}/{task}: {ids}"


@pytest.mark.parametrize("skill,task,min_cases", EXPECTED_DATASETS)
def test_dataset_expected_output_contains_is_list(skill: str, task: str, min_cases: int):
    """expected_output_contains is a list of strings (not a bare string)."""
    data = load_dataset(skill, task)
    for case in data["cases"]:
        val = case["expected_output_contains"]
        assert isinstance(val, list), (
            f"Case {case['id']} in {skill}/{task}: expected_output_contains must be list, got {type(val)}"
        )
        assert all(isinstance(s, str) for s in val), (
            f"Case {case['id']} in {skill}/{task}: expected_output_contains must be list of strings"
        )
