"""Tests for skills/tableau-data-app-preview/scripts/build_preview.py.

Each test copies the fixture app into tmp_path, so the builder output
(mock/versions, mock/preview.html, logs) never lands in the fixture folder.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

def _find_package_twbx() -> Path | None:
    """Find package_twbx.py: the sibling skill (plugin repo), else the newest installed Tableau plugin.

    Returns:
        The script path, or None if the Tableau plugin is not installed.
    """
    sibling = SKILL_DIR.parent / "tableau-data-app-authoring" / "scripts" / "package_twbx.py"
    if sibling.is_file():
        return sibling
    # User-level copy (~/.claude/skills/): the plugin sits in the plugin cache, one folder per version.
    installed = (Path.home() / ".claude" / "plugins" / "cache" / "tableau-plugin" / "tableau").glob(
        "*/skills/tableau-data-app-authoring/scripts/package_twbx.py")
    return max(installed, default=None,
               key=lambda path: [int(part) for part in path.parents[3].name.split(".") if part.isdigit()])


PACKAGE_TWBX = _find_package_twbx()


def _load_builder():
    """Import build_preview.py from the skill folder (it is not a package)."""
    spec = importlib.util.spec_from_file_location("build_preview", SKILL_DIR / "scripts" / "build_preview.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = _load_builder()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A copy of the fixture app with mock/mock-data.json in place."""
    app_dir = tmp_path / "Test App"
    shutil.copytree(FIXTURES / "app", app_dir)
    (app_dir / "mock").mkdir()
    shutil.copy(FIXTURES / "mock-data.json", app_dir / "mock" / "mock-data.json")
    return app_dir


@pytest.fixture
def content_dir(workspace: Path) -> Path:
    return workspace / "Packages" / "com.test.app" / "content"


@pytest.fixture
def mock_data() -> dict:
    return json.loads((FIXTURES / "mock-data.json").read_text(encoding="utf-8"))


@pytest.fixture
def stub_js() -> str:
    return (SKILL_DIR / "assets" / "tableau-stub.js").read_text(encoding="utf-8")


def test_replaces_tableau_lib_with_stub_and_mock(content_dir, mock_data, stub_js):
    page = builder.build_version_page(content_dir, mock_data, stub_js)
    assert "window.__DATA_APP_MOCK__ =" in page
    assert "function canonicalJson" in page  # the stub itself
    assert "real lib loaded" not in page  # the real library is dropped


def test_inlines_all_local_assets_in_order(content_dir, mock_data, stub_js):
    page = builder.build_version_page(content_dir, mock_data, stub_js)
    css = (content_dir / "src" / "styles.css").read_text(encoding="utf-8").strip()
    assert f"<style>\n{css}" in page
    assert page.index("__DATA_APP_MOCK__") < page.index("function canonicalJson")
    assert page.index("function canonicalJson") < page.index("window.chartLib =")
    assert page.index("window.chartLib =") < page.index("'מכירות'")
    assert 'src="src/' not in page
    assert 'href="src/' not in page


def test_inline_escapes_script_close(content_dir, mock_data, stub_js):
    mock_data["queries"][0]["data"].append({"Category": "</b>"})
    page = builder.build_version_page(content_dir, mock_data, stub_js)
    assert '"<\\/script>"' in page  # from chart-lib.js
    assert "<\\/b>" in page  # from the mock JSON
    assert "</b>" not in page


def test_missing_asset_fails(content_dir, mock_data, stub_js):
    (content_dir / "src" / "chart-lib.js").unlink()
    with pytest.raises(FileNotFoundError, match="src/chart-lib.js"):
        builder.build_version_page(content_dir, mock_data, stub_js)


@pytest.mark.parametrize("escape", ["../secret.js", "ABSOLUTE"])
def test_asset_outside_content_fails(content_dir, mock_data, stub_js, escape):
    # The page gets published, so a file outside content/ must never be inlined.
    secret = content_dir.parent / "secret.js"
    secret.write_text("SECRET_TOKEN", encoding="utf-8")
    reference = secret.as_posix() if escape == "ABSOLUTE" else escape
    index = content_dir / "index.html"
    index.write_text(index.read_text(encoding="utf-8").replace("src/chart-lib.js", reference),
                     encoding="utf-8")
    with pytest.raises(ValueError, match="outside content/"):
        builder.build_version_page(content_dir, mock_data, stub_js)


def test_utf8_round_trip(workspace):
    version_path = builder.add_version(workspace, workspace / "mock" / "mock-data.json", "Initial")
    text = version_path.read_bytes().decode("utf-8")
    assert "מכירות" in text  # from app.js
    assert "רהיטים" in text  # from the mock rows


def test_versions_append_and_number(workspace):
    mock_json = workspace / "mock" / "mock-data.json"
    first = builder.add_version(workspace, mock_json, "Initial")
    second = builder.add_version(workspace, mock_json, "Sorted desc")
    assert first.name == "01-initial.html"
    assert second.name == "02-sorted-desc.html"
    versions = json.loads((workspace / "mock" / "versions.json").read_text(encoding="utf-8"))
    assert [v["file"] for v in versions] == ["versions/01-initial.html", "versions/02-sorted-desc.html"]
    assert [v["label"] for v in versions] == ["Initial", "Sorted desc"]


def test_replace_last_rebuilds_latest_version(workspace):
    # An unpublished draft is rebuilt under its own number; earlier versions stay.
    mock_json = workspace / "mock" / "mock-data.json"
    first = builder.add_version(workspace, mock_json, "Initial")
    builder.add_version(workspace, mock_json, "Draft")
    replaced = builder.add_version(workspace, mock_json, "Fixed draft", replace_last=True)
    assert replaced.name == "02-fixed-draft.html"
    assert not (workspace / "mock" / "versions" / "02-draft.html").exists()
    assert first.is_file()
    versions = json.loads((workspace / "mock" / "versions.json").read_text(encoding="utf-8"))
    assert [v["file"] for v in versions] == ["versions/01-initial.html", "versions/02-fixed-draft.html"]


def test_replace_last_without_versions_fails(workspace):
    with pytest.raises(ValueError, match="no version to replace"):
        builder.add_version(workspace, workspace / "mock" / "mock-data.json", "v1", replace_last=True)


def test_cli_replace_last_flag(workspace):
    assert builder.main([str(workspace), "--label", "v1"]) == 0
    assert builder.main([str(workspace), "--label", "v1 fixed", "--replace-last"]) == 0
    versions = json.loads((workspace / "mock" / "versions.json").read_text(encoding="utf-8"))
    assert [v["file"] for v in versions] == ["versions/01-v1-fixed.html"]


def test_shell_lists_tabs_and_compare(workspace):
    mock_json = workspace / "mock" / "mock-data.json"
    builder.add_version(workspace, mock_json, "Initial")
    builder.add_version(workspace, mock_json, "Sorted desc")
    shell = builder.build_shell(workspace).read_text(encoding="utf-8")
    assert "<title>Test App preview</title>" in shell
    assert shell.count('data-tab="versions/') == 2
    assert 'data-tab="versions/02-sorted-desc.html" aria-selected="true"' in shell
    assert 'data-tab="versions/01-initial.html" aria-selected="false"' in shell
    assert 'src="versions/01-initial.html"' in shell
    assert 'data-tab="compare"' in shell
    assert shell.count("<select") == 2


def test_shell_hidden_rule_beats_display(workspace):
    # iframe { display: block } overrides the browser's [hidden] rule, so the shell needs its own
    builder.add_version(workspace, workspace / "mock" / "mock-data.json", "Initial")
    shell = builder.build_shell(workspace).read_text(encoding="utf-8")
    assert "[hidden] { display: none !important; }" in shell


def test_single_quoted_tags_inlined(content_dir, mock_data, stub_js):
    (content_dir / "index.html").write_text(
        "<link rel='stylesheet' href='src/styles.css'>\n<div id=\"app\"></div>\n"
        "<script src='src/tableau.extensions.1.latest.min.js'></script>\n"
        "<script src='src/chart-lib.js'></script>\n<script src='src/app.js'></script>\n", encoding="utf-8")
    page = builder.build_version_page(content_dir, mock_data, stub_js)
    assert "src='src/" not in page and "href='src/" not in page
    assert "function canonicalJson" in page and "window.chartLib =" in page and "<style>" in page


def test_defer_script_runs_after_body(content_dir, mock_data, stub_js):
    # A webpack build puts <script defer src> in <head>; inline code would run before #app exists
    (content_dir / "index.html").write_text(
        '<html><head><script src="src/tableau.extensions.1.latest.min.js"></script>'
        '<script src="src/chart-lib.js"></script><script defer="defer" src="src/app.js"></script></head>'
        '<body><div id="app"></div></body></html>', encoding="utf-8")
    page = builder.build_version_page(content_dir, mock_data, stub_js)
    assert page.index('<div id="app">') < page.index("'מכירות'") < page.index("</body>")


def test_module_type_kept(content_dir, mock_data, stub_js):
    (content_dir / "index.html").write_text(
        '<div id="app"></div><script type="module" src="src/app.js"></script>', encoding="utf-8")
    page = builder.build_version_page(content_dir, mock_data, stub_js)
    assert '<script type="module">' in page


def test_bom_inputs_are_read(workspace, content_dir):
    # PowerShell 5.1 Out-File writes UTF-8 with a BOM
    mock_json = workspace / "mock" / "mock-data.json"
    mock_json.write_text(mock_json.read_text(encoding="utf-8"), encoding="utf-8-sig")
    css = content_dir / "src" / "styles.css"
    css.write_text(css.read_text(encoding="utf-8"), encoding="utf-8-sig")
    page = builder.add_version(workspace, mock_json, "Bom").read_text(encoding="utf-8")
    assert "﻿" not in page


def test_size_limit_fails(workspace, monkeypatch):
    monkeypatch.setattr(builder, "MAX_BYTES", 100)
    with pytest.raises(ValueError, match="MB"):
        builder.add_version(workspace, workspace / "mock" / "mock-data.json", "Too big")


@pytest.mark.skipif(PACKAGE_TWBX is None, reason="Tableau plugin not installed: no package_twbx.py")
def test_mock_folder_not_packaged(workspace, tmp_path):
    builder.add_version(workspace, workspace / "mock" / "mock-data.json", "Initial")
    builder.build_shell(workspace)
    output = tmp_path / "Test App.twbx"
    result = subprocess.run([sys.executable, str(PACKAGE_TWBX), str(workspace), str(output)],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    names = zipfile.ZipFile(output).namelist()
    assert names, "package is empty"
    assert not [name for name in names if name.startswith("mock/")]


def test_cli_prints_only_shell_path(workspace, capsys):
    exit_code = builder.main([str(workspace), "--label", "v1"])
    assert exit_code == 0
    assert capsys.readouterr().out == f"{workspace / 'mock' / 'preview.html'}\n"


def test_tableau_lib_with_query_string_replaced(content_dir, mock_data, stub_js):
    (content_dir / "index.html").write_text(
        '<div id="app"></div><script src="src/tableau.extensions.1.latest.min.js?v=1"></script>',
        encoding="utf-8")
    page = builder.build_version_page(content_dir, mock_data, stub_js)
    assert "function canonicalJson" in page
    assert "real lib loaded" not in page


def test_inline_escapes_comment_open(content_dir, mock_data, stub_js):
    # '<!--' then '<script' puts the HTML parser in the double-escaped state
    (content_dir / "src" / "chart-lib.js").write_text(
        'window.chartLib = { trap: "<!--<script>" };', encoding="utf-8")
    page = builder.build_version_page(content_dir, mock_data, stub_js)
    assert '"<\\!--<script>"' in page
    assert "<!--" not in page


def test_cli_bad_workspace_creates_nothing(tmp_path, capsys):
    typo = tmp_path / "Tset App"
    exit_code = builder.main([str(typo), "--label", "v1"])
    assert exit_code == 1
    assert not typo.exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert "Packages" in captured.err


@pytest.mark.parametrize("break_mock, missing", [
    (lambda mock: mock.pop("datasource"), "datasource"),
    (lambda mock: mock["datasource"].pop("id"), "id"),
    (lambda mock: mock["datasource"].pop("name"), "name"),
    (lambda mock: mock.pop("queries"), "queries"),
    (lambda mock: mock["queries"][0].pop("data"), "data"),
])
def test_mock_missing_key_fails(workspace, break_mock, missing):
    mock_json = workspace / "mock" / "mock-data.json"
    mock = json.loads(mock_json.read_text(encoding="utf-8"))
    break_mock(mock)
    mock_json.write_text(json.dumps(mock), encoding="utf-8")
    with pytest.raises(ValueError, match=f'"{missing}"'):
        builder.add_version(workspace, mock_json, "Broken")
