"""Tests for Obsidian vault DataHub ingestion source."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from obsidian_source.source import ObsidianSource, ObsidianSourceConfig


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    """Create a minimal Obsidian vault for testing."""
    # Root file
    (tmp_path / "Home.md").write_text("# Home\nWelcome to the vault.")

    # Project note with frontmatter
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "Platform.md").write_text(dedent("""\
        ---
        title: Platform Monorepo
        tags: [infra, k8s]
        status: active
        ---
        # Platform
        The main infrastructure repo.
        Links to [[Home]] and [[Music Production]].
    """))

    # Area note
    areas = tmp_path / "areas"
    areas.mkdir()
    (areas / "Tech and Career.md").write_text("# Tech\nML engineering and platform work.")

    # Template (should be excluded)
    templates = tmp_path / "_templates"
    templates.mkdir()
    (templates / "daily-note.md").write_text("# {{date}}")

    # Archive nested
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "Old Note.md").write_text("Archived content.")

    return tmp_path


def _make_source(vault_path: str) -> ObsidianSource:
    config = ObsidianSourceConfig(vault_path=vault_path)
    # Minimal context mock
    from unittest.mock import MagicMock
    ctx = MagicMock()
    ctx.graph = None
    return ObsidianSource(config, ctx)


class TestObsidianSource:
    def test_scans_markdown_files(self, vault_dir: Path) -> None:
        source = _make_source(str(vault_dir))
        workunits = list(source.get_workunits())
        report = source.get_report()

        # 5 .md files total, 1 excluded (_templates/)
        assert report.files_scanned == 5
        assert report.files_skipped == 1
        assert report.files_ingested == 4

    def test_excludes_templates(self, vault_dir: Path) -> None:
        source = _make_source(str(vault_dir))
        workunits = list(source.get_workunits())

        # No workunit should reference _templates
        ids = [wu.id for wu in workunits]
        assert not any("_templates" in wid for wid in ids)

    def test_extracts_frontmatter_tags(self, vault_dir: Path) -> None:
        source = _make_source(str(vault_dir))
        workunits = list(source.get_workunits())

        # Find the Platform tags workunit
        tag_wus = [wu for wu in workunits if "Platform-tags" in wu.id]
        assert len(tag_wus) == 1

        mcp = tag_wus[0].mcp
        tag_urns = [t.tag for t in mcp.aspect.tags]
        assert any("obsidian:infra" in urn for urn in tag_urns)
        assert any("obsidian:k8s" in urn for urn in tag_urns)
        assert any("obsidian:projects" in urn for urn in tag_urns)

    def test_extracts_wiki_links(self, vault_dir: Path) -> None:
        source = _make_source(str(vault_dir))
        workunits = list(source.get_workunits())

        # Find Platform properties
        prop_wus = [wu for wu in workunits if "Platform-properties" in wu.id]
        assert len(prop_wus) == 1

        props = prop_wus[0].mcp.aspect
        links = props.customProperties.get("wiki_links", "")
        assert "Home" in links
        assert "Music Production" in links

    def test_folder_as_tag(self, vault_dir: Path) -> None:
        source = _make_source(str(vault_dir))
        workunits = list(source.get_workunits())

        # archive/Old Note should get obsidian:archive tag
        tag_wus = [wu for wu in workunits if "Old Note-tags" in wu.id]
        assert len(tag_wus) == 1
        tag_urns = [t.tag for t in tag_wus[0].mcp.aspect.tags]
        assert any("obsidian:archive" in urn for urn in tag_urns)

    def test_nonexistent_vault(self) -> None:
        source = _make_source("/nonexistent/vault")
        workunits = list(source.get_workunits())
        assert len(workunits) == 0
        assert source.get_report().failures
