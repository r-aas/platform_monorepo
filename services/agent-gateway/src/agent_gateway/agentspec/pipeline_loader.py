"""Load multi-agent pipeline YAML files into PipelineDefinition models."""

from pathlib import Path

import yaml

from agent_gateway.models import PipelineDefinition


def load_pipeline_yaml(path: Path) -> PipelineDefinition:
    """Load a pipeline YAML file and return a validated PipelineDefinition."""
    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Invalid YAML structure in {path}")

    if not raw.get("name"):
        raise ValueError(f"Pipeline YAML missing required field 'name' in {path}")

    pipeline = PipelineDefinition.model_validate(raw)

    # Validate that depends_on references point to real stage names
    stage_names = {s.name for s in pipeline.stages}
    for stage in pipeline.stages:
        for dep in stage.depends_on:
            if dep not in stage_names:
                raise ValueError(
                    f"Stage '{stage.name}' depends_on unknown stage '{dep}' in {path}"
                )

    return pipeline


def load_pipelines_dir(pipelines_dir: Path) -> list[PipelineDefinition]:
    """Load all pipeline YAML files from a directory."""
    pipelines = []
    for path in sorted(pipelines_dir.glob("*.yaml")):
        pipelines.append(load_pipeline_yaml(path))
    return pipelines
