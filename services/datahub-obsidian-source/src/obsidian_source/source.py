"""Obsidian vault DataHub ingestion source.

Reads markdown files from an Obsidian vault directory and emits them as
DataHub Documentation entities with tags derived from folder structure
and YAML frontmatter.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml
from datahub.configuration.common import ConfigModel
from datahub.ingestion.api.common import PipelineContext
from datahub.ingestion.api.decorators import config_class, platform_name
from datahub.ingestion.api.source import Source, SourceReport
from datahub.ingestion.api.workunit import MetadataWorkUnit
from datahub.metadata.schema_classes import (
    AuditStampClass,
    DatasetPropertiesClass,
    GlobalTagsClass,
    InstitutionalMemoryClass,
    InstitutionalMemoryMetadataClass,
    TagAssociationClass,
)
from datahub.emitter.mce_builder import make_dataset_urn, make_tag_urn

logger = logging.getLogger(__name__)


class ObsidianSourceConfig(ConfigModel):
    """Configuration for the Obsidian vault ingestion source."""

    vault_path: str = ""
    platform: str = "obsidian"
    env: str = "PROD"
    exclude_patterns: list[str] = field(default_factory=lambda: ["_templates/*", "_attachments/*"])


@dataclass
class ObsidianSourceReport(SourceReport):
    files_scanned: int = 0
    files_ingested: int = 0
    files_skipped: int = 0


@platform_name("Obsidian")
@config_class(ObsidianSourceConfig)
class ObsidianSource(Source):
    """DataHub source that ingests Obsidian vault markdown files as dataset entities."""

    config: ObsidianSourceConfig
    report: ObsidianSourceReport

    def __init__(self, config: ObsidianSourceConfig, ctx: PipelineContext) -> None:
        super().__init__(ctx)
        self.config = config
        self.report = ObsidianSourceReport()

    @classmethod
    def create(cls, config_dict: dict[str, Any], ctx: PipelineContext) -> "ObsidianSource":
        config = ObsidianSourceConfig.parse_obj(config_dict)
        return cls(config, ctx)

    def get_workunits(self) -> Iterable[MetadataWorkUnit]:
        vault = Path(self.config.vault_path).expanduser().resolve()
        if not vault.is_dir():
            self.report.report_failure("vault_path", f"Not a directory: {vault}")
            return

        for md_file in sorted(vault.rglob("*.md")):
            self.report.files_scanned += 1
            rel_path = md_file.relative_to(vault)

            # Check exclude patterns
            if self._should_exclude(str(rel_path)):
                self.report.files_skipped += 1
                continue

            yield from self._emit_document(md_file, rel_path)
            self.report.files_ingested += 1

    def _should_exclude(self, rel_path: str) -> bool:
        import fnmatch

        return any(fnmatch.fnmatch(rel_path, pat) for pat in self.config.exclude_patterns)

    def _emit_document(self, md_file: Path, rel_path: Path) -> Iterable[MetadataWorkUnit]:
        content = md_file.read_text(errors="replace")
        frontmatter = self._parse_frontmatter(content)
        body = self._strip_frontmatter(content)

        # Build dataset URN from file path
        dataset_name = str(rel_path).removesuffix(".md").replace("/", ".")
        urn = make_dataset_urn(
            platform=self.config.platform,
            name=dataset_name,
            env=self.config.env,
        )

        # Extract metadata
        title = frontmatter.get("title", rel_path.stem)
        tags = self._extract_tags(frontmatter, rel_path)
        description = self._extract_description(body)
        links = self._extract_wiki_links(body)

        # Dataset properties
        props = DatasetPropertiesClass(
            name=title,
            description=description,
            customProperties={
                "vault_path": str(rel_path),
                "folder": str(rel_path.parent) if str(rel_path.parent) != "." else "root",
                "word_count": str(len(body.split())),
                "wiki_links": ",".join(links[:20]),
                **{k: str(v) for k, v in frontmatter.items() if isinstance(v, (str, int, float, bool))},
            },
        )
        yield MetadataWorkUnit(
            id=f"{dataset_name}-properties",
            mce=None,
            mcp=self._make_mcp(urn, "datasetProperties", props),
        )

        # Tags
        if tags:
            global_tags = GlobalTagsClass(
                tags=[TagAssociationClass(tag=make_tag_urn(t)) for t in tags]
            )
            yield MetadataWorkUnit(
                id=f"{dataset_name}-tags",
                mce=None,
                mcp=self._make_mcp(urn, "globalTags", global_tags),
            )

    def _make_mcp(self, urn: str, aspect_name: str, aspect: Any) -> Any:
        from datahub.emitter.mcp import MetadataChangeProposalWrapper

        return MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspectName=aspect_name,
            aspect=aspect,
        )

    def _parse_frontmatter(self, content: str) -> dict[str, Any]:
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not match:
            return {}
        try:
            return yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            return {}

    def _strip_frontmatter(self, content: str) -> str:
        return re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL)

    def _extract_tags(self, frontmatter: dict, rel_path: Path) -> list[str]:
        tags: list[str] = []
        # Folder as tag
        folder = str(rel_path.parent)
        if folder != ".":
            tags.append(f"obsidian:{folder.split('/')[0]}")
        # Frontmatter tags
        fm_tags = frontmatter.get("tags", [])
        if isinstance(fm_tags, list):
            tags.extend(f"obsidian:{t}" for t in fm_tags)
        elif isinstance(fm_tags, str):
            tags.extend(f"obsidian:{t.strip()}" for t in fm_tags.split(","))
        return tags

    def _extract_description(self, body: str) -> str:
        """First non-empty, non-heading line as description."""
        for line in body.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:500]
        return ""

    def _extract_wiki_links(self, body: str) -> list[str]:
        return re.findall(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]", body)

    def get_report(self) -> ObsidianSourceReport:
        return self.report

    def close(self) -> None:
        pass
