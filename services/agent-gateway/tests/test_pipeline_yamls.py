"""Tests for multi-agent pipeline YAML definitions — validate schema + required fields."""

from pathlib import Path

from agent_gateway.agentspec.pipeline_loader import load_pipeline_yaml

# Pipelines directory is at monorepo_root/pipelines/
MONOREPO_ROOT = Path(__file__).parents[3]
PIPELINES_DIR = MONOREPO_ROOT / "pipelines"

VALID_ON_ERROR_VALUES = {"stop", "continue", "retry"}


def load_pipeline(name: str):
    """Load and validate a pipeline YAML from the pipelines/ directory."""
    path = PIPELINES_DIR / f"{name}.yaml"
    return load_pipeline_yaml(path)


# ──────────────────────────────────────────────────────────────────────────────
# E.03 — model-deploy-pipeline
# ──────────────────────────────────────────────────────────────────────────────


def test_pipeline_loads():
    pipeline = load_pipeline("model-deploy-pipeline")
    assert pipeline.name == "model-deploy-pipeline"


def test_pipeline_has_description():
    pipeline = load_pipeline("model-deploy-pipeline")
    assert pipeline.description


def test_pipeline_has_stages():
    pipeline = load_pipeline("model-deploy-pipeline")
    assert len(pipeline.stages) >= 2


def test_pipeline_stages_have_required_fields():
    pipeline = load_pipeline("model-deploy-pipeline")
    for stage in pipeline.stages:
        assert stage.name, f"Stage missing name: {stage}"
        assert stage.agent, f"Stage missing agent: {stage.name}"


def test_pipeline_stage_depends_on_valid_refs():
    pipeline = load_pipeline("model-deploy-pipeline")
    stage_names = {s.name for s in pipeline.stages}
    for stage in pipeline.stages:
        for dep in stage.depends_on:
            assert dep in stage_names, (
                f"Stage '{stage.name}' depends_on unknown stage '{dep}'"
            )


def test_pipeline_routing_on_error_is_valid():
    pipeline = load_pipeline("model-deploy-pipeline")
    assert pipeline.routing.on_error in VALID_ON_ERROR_VALUES


def test_pipeline_version_is_set():
    pipeline = load_pipeline("model-deploy-pipeline")
    assert pipeline.version


def test_pipeline_component_type():
    pipeline = load_pipeline("model-deploy-pipeline")
    assert pipeline.component_type == "Pipeline"
