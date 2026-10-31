"""Extract Keep-a-Changelog lines for a release (used after memory update)."""

from __future__ import annotations

from cairnkit.install_source import release_notes

SAMPLE = """# Changelog

## [Unreleased]

## [0.3.1] - 2026-10-30

### Added

- New cairn animation for memory update.
- Version source on --version (deferred).

### Fixed

- Strip uv git pins.

## [0.3.0] - 2026-10-30

### Added

- memory docs atlas.

## [0.2.0] - 2026-10-26

Baseline.
"""


def test_release_notes_returns_new_section_lines():
    lines = release_notes(SAMPLE, "0.3.0", "0.3.1")
    joined = "\n".join(lines)
    assert "New cairn animation for memory update." in joined
    assert "Strip uv git pins." in joined
    assert "memory docs atlas." not in joined
    assert "Unreleased" not in joined


def test_release_notes_empty_when_version_missing():
    assert release_notes(SAMPLE, "0.3.0", "9.9.9") == []
    assert release_notes(SAMPLE, "0.3.0", None) == []
    assert release_notes("", "0.3.0", "0.3.1") == []


def test_release_notes_skips_blank_only_lines():
    lines = release_notes(SAMPLE, "0.3.0", "0.3.1")
    assert all(line.strip() for line in lines)


def test_release_notes_from_path(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(SAMPLE, encoding="utf-8")
    lines = release_notes(path, "0.3.0", "0.3.1")
    assert any("cairn animation" in line for line in lines)
