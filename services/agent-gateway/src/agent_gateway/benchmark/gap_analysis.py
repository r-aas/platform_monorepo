"""Skill gap analysis — F.03.

Identifies missing skills (referenced by agents but not defined) and
unused skills (defined but not referenced by any agent).
Pure functions: no side effects, fully testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_gateway.models import AgentDefinition, SkillDefinition


@dataclass
class GapAnalysisResult:
    missing_skills: set[str] = field(default_factory=set)  # referenced but not defined
    unused_skills: set[str] = field(default_factory=set)   # defined but not referenced
    covered_skills: set[str] = field(default_factory=set)  # defined AND referenced

    @property
    def coverage_ratio(self) -> float:
        """Fraction of referenced skills that are defined (1.0 if none referenced)."""
        total_referenced = len(self.covered_skills) + len(self.missing_skills)
        if total_referenced == 0:
            return 1.0
        return len(self.covered_skills) / total_referenced


def find_referenced_skills(agents: list[AgentDefinition]) -> set[str]:
    """Collect all skill names referenced across all agent definitions."""
    result: set[str] = set()
    for agent in agents:
        result.update(agent.skills)
    return result


def find_defined_skills(skills: list[SkillDefinition]) -> set[str]:
    """Collect all skill names that are defined in the registry."""
    return {s.name for s in skills}


def analyze_skill_gaps(
    referenced: set[str],
    defined: set[str],
) -> GapAnalysisResult:
    """Compute gap analysis from sets of referenced and defined skill names."""
    covered = referenced & defined
    missing = referenced - defined
    unused = defined - referenced
    return GapAnalysisResult(
        missing_skills=missing,
        unused_skills=unused,
        covered_skills=covered,
    )
