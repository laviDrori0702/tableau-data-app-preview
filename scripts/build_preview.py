#!/usr/bin/env python3
"""Build a mock preview of a Tableau data app for a Claude artifact.

Each run adds one version page and rebuilds the shell page:
  <App Name>/mock/versions/NN-<label slug>.html   one self-contained version
  <App Name>/mock/versions.json                   version list (file, label, created)
  <App Name>/mock/preview.html                    shell: one tab per version + Compare

A version page is the app's content/index.html with every local CSS and JS file
inlined. The Tableau Extensions API library is replaced by the mock data
(window.__DATA_APP_MOCK__) and the stub assets/tableau-stub.js. The mock/ folder
sits outside Packages/, so package_twbx.py never packs it.

Usage: python build_preview.py <workspaceDir> --label "<text>" [--mock <mock-data.json>]
The only stdout output is the shell page path.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

MAX_BYTES = 16 * 1024 * 1024  # Artifact limit per page and per file
STUB_PATH = Path(__file__).resolve().parent.parent / "assets" / "tableau-stub.js"

# ponytail: regex tag rewrite; switch to html.parser if apps use unusual tag shapes
# Groups: attributes before src, quote, src value, attributes after src. Both quote styles.
SCRIPT_TAG = re.compile(r'<script\b([^>]*?)\bsrc=(["\'])(.+?)\2([^>]*)>\s*</script>', re.IGNORECASE)
STYLESHEET_TAG = re.compile(r'<link\b[^>]*?\brel=["\']?stylesheet["\']?[^>]*>', re.IGNORECASE)
HREF_ATTR = re.compile(r'\bhref=(["\'])(.+?)\1', re.IGNORECASE)
DEFER_ATTR = re.compile(r'\bdefer\b', re.IGNORECASE)
MODULE_ATTR = re.compile(r'\btype=["\']?module\b', re.IGNORECASE)
BODY_CLOSE = re.compile(r'</body\s*>', re.IGNORECASE)
TABLEAU_LIB = re.compile(r'(^|/)tableau\.extensions\.[^/]*\.js(\?.*)?$')  # optional ?v=1 cache buster
EXTERNAL = re.compile(r'^(https?:)?//', re.IGNORECASE)

logger = logging.getLogger("build_preview")


def _escape_inline_script(text: str) -> str:
    """Stop inlined code from closing its <script> tag early.

    Args:
        text: JavaScript source.

    Returns:
        The source with each '</script' written as '<\\/script' and each '<!--' as '<\\!--'.
    """
    # '<!--' then '<script' puts the HTML parser in the double-escaped state; '<\!--' is the same JS string.
    text = text.replace("<!--", "<\\!--")
    return re.sub(r'</script', r'<\\/script', text, flags=re.IGNORECASE)


def _read_asset(content_dir: Path, reference: str) -> str:
    """Read a file that index.html references.

    Args:
        content_dir: The package content/ folder.
        reference: The src or href value, for example 'src/app.js'.

    Returns:
        The file text.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    path = content_dir / reference.split("?")[0]
    if not path.is_file():
        raise FileNotFoundError(f"Missing asset referenced by index.html: {reference}")
    return path.read_text(encoding="utf-8-sig")  # utf-8-sig drops a BOM (PowerShell 5.1 writes one)


def build_version_page(content_dir: Path, mock_data: dict, stub_js: str) -> str:
    """Turn the app's index.html into one self-contained preview page.

    Args:
        content_dir: The package content/ folder that holds index.html.
        mock_data: Parsed mock-data.json (datasource, metadata, queries).
        stub_js: Source of assets/tableau-stub.js.

    Returns:
        The full HTML text of the version page.

    Raises:
        FileNotFoundError: If index.html or a local asset is missing.
    """
    page = _read_asset(content_dir, "index.html")
    # '</' inside the JSON would end the <script> tag; '<\/' is the same JSON string.
    mock_json = json.dumps(mock_data, ensure_ascii=False).replace("</", "<\\/")

    deferred_scripts = []  # inline code ignores 'defer', so these move to the end of <body>

    def replace_script(match: re.Match) -> str:
        source = match.group(3)
        attributes = f"{match.group(1)} {match.group(4)}"
        if EXTERNAL.match(source):
            logger.warning(f"External script kept as a link (the artifact may block it): {source}")
            return match.group(0)
        if TABLEAU_LIB.search(source):
            # The real API only works inside Tableau; the stub serves the mock rows.
            return (f"<script>window.__DATA_APP_MOCK__ = {mock_json};</script>\n"
                    f"<script>\n{_escape_inline_script(stub_js)}\n</script>")
        # An inline module script is deferred by the browser, so it can stay in place.
        open_tag = '<script type="module">' if MODULE_ATTR.search(attributes) else "<script>"
        inline = f"{open_tag}\n{_escape_inline_script(_read_asset(content_dir, source))}\n</script>"
        if DEFER_ATTR.search(attributes) and not MODULE_ATTR.search(attributes):
            deferred_scripts.append(inline)
            return ""
        return inline

    def replace_stylesheet(match: re.Match) -> str:
        href = HREF_ATTR.search(match.group(0))
        if not href or EXTERNAL.match(href.group(2)):
            logger.warning(f"Stylesheet kept as a link: {match.group(0)}")
            return match.group(0)
        return f"<style>\n{_read_asset(content_dir, href.group(2)).strip()}\n</style>"

    page = SCRIPT_TAG.sub(replace_script, page)
    page = STYLESHEET_TAG.sub(replace_stylesheet, page)
    if deferred_scripts:
        # Deferred scripts run after parsing, in document order: the end of <body> keeps both.
        tail = "\n".join(deferred_scripts) + "\n"
        body_close = BODY_CLOSE.search(page)
        page = (page[:body_close.start()] + tail + page[body_close.start():]) if body_close else page + tail
    return page


def _find_content_dir(workspace: Path) -> Path:
    """Find the single Packages/<id>/content folder of a workspace.

    Args:
        workspace: The app workspace folder.

    Returns:
        The content/ folder.

    Raises:
        ValueError: If there is not exactly one package content folder.
    """
    found = sorted(path for path in (workspace / "Packages").glob("*/content") if path.is_dir())
    if len(found) != 1:
        raise ValueError(f"Expected one Packages/<id>/content folder in {workspace}, found {len(found)}")
    return found[0]


def _slugify(label: str) -> str:
    """Make a file-name slug from a version label (non-ASCII labels become 'version')."""
    return re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-') or "version"


def _load_versions(workspace: Path) -> list:
    """Read mock/versions.json, or return an empty list if it does not exist."""
    path = workspace / "mock" / "versions.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def _check_mock(mock_data: object) -> None:
    """Check the keys that tableau-stub.js reads from mock-data.json.

    Args:
        mock_data: Parsed mock-data.json.

    Raises:
        ValueError: If a key is missing; the message names it.
    """
    datasource = mock_data.get("datasource") if isinstance(mock_data, dict) else None
    if not isinstance(datasource, dict) or not {"id", "name"} <= datasource.keys():
        raise ValueError('mock-data.json needs "datasource" with "id" and "name"')
    queries = mock_data.get("queries")
    if not isinstance(queries, list) or not all(
            isinstance(entry, dict) and {"query", "data"} <= entry.keys() for entry in queries):
        raise ValueError('mock-data.json needs "queries" as a list of {"query": ..., "data": [...]}')


def add_version(workspace: Path, mock_json: Path, label: str, replace_last: bool = False) -> Path:
    """Build a new version page and add it to mock/versions.json.

    Args:
        workspace: The app workspace folder.
        mock_json: Path of mock-data.json.
        label: Tab label for the stakeholder, for example 'v2 sorted by sales'.
        replace_last: Delete the latest version first and reuse its number. Only for a
            version that is not published yet: a published tab must never change.

    Returns:
        Path of the new version page.

    Raises:
        FileNotFoundError: If the mock file or an app asset is missing.
        ValueError: If the page is larger than MAX_BYTES, the workspace is not valid,
            or replace_last is set and there is no version to replace.
    """
    mock_data = json.loads(mock_json.read_text(encoding="utf-8-sig"))
    _check_mock(mock_data)  # a missing key shows in the browser only as "Cannot read properties of undefined"
    page = build_version_page(_find_content_dir(workspace), mock_data, STUB_PATH.read_text(encoding="utf-8"))
    size = len(page.encode("utf-8"))
    if size > MAX_BYTES:
        raise ValueError(f"Version page is {size / 1048576:.1f} MB; the artifact limit is "
                         f"{MAX_BYTES / 1048576:.0f} MB. Remove large vendored files or rows.")

    versions = _load_versions(workspace)
    if replace_last:
        if not versions:
            raise ValueError("--replace-last: no version to replace; build the first version without it")
        replaced = versions.pop()
        (workspace / "mock" / replaced["file"]).unlink(missing_ok=True)
        logger.info(f"Replacing {replaced['file']}")
    file_name = f"{len(versions) + 1:02d}-{_slugify(label)}.html"
    version_path = workspace / "mock" / "versions" / file_name
    version_path.parent.mkdir(parents=True, exist_ok=True)
    version_path.write_text(page, encoding="utf-8")

    versions.append({"file": f"versions/{file_name}", "label": label,
                     "created": datetime.now().isoformat(timespec="seconds")})
    (workspace / "mock" / "versions.json").write_text(
        json.dumps(versions, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Added version {file_name} ({size / 1024:.0f} KB)")
    return version_path


SHELL_TEMPLATE = """<title>{title}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500&family=IBM+Plex+Sans:wght@400;600&display=swap">
<style>
/* Layout: header, then a wrapping tab row, then one large frame (or two frames side by side in Compare). */
:root {{
  --bg: #f3f5f7; --surface: #ffffff; --fg: #1c232b; --muted: #5d6874; --line: #cfd6de; --accent: #1f6f8b;
  --font-ui: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  --font-data: "IBM Plex Mono", Consolas, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #12171c; --surface: #1a2128; --fg: #e3e8ed; --muted: #97a3af; --line: #33404c; --accent: #6cb6cf; color-scheme: dark }} }}
:root[data-theme="dark"] {{
  --bg: #12171c; --surface: #1a2128; --fg: #e3e8ed; --muted: #97a3af; --line: #33404c; --accent: #6cb6cf; color-scheme: dark }}
body {{ background: var(--bg); color: var(--fg); font-family: var(--font-ui);
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  padding-block: 20px; }}
[hidden] {{ display: none !important; }}
header {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 16px; margin-bottom: 16px; }}
h1 {{ font-size: 20px; font-weight: 600; margin: 0; text-wrap: balance; }}
.note {{ color: var(--muted); font-size: 13px; }}
nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }}
nav button {{ font: inherit; font-size: 13px; padding: 6px 12px; border: 1px solid var(--line); border-radius: 4px;
  background: var(--surface); color: var(--fg); cursor: pointer; }}
nav button .num {{ font-family: var(--font-data); color: var(--muted); margin-right: 6px; }}
nav button[aria-selected="true"] {{ border-color: var(--accent); color: var(--accent); box-shadow: inset 0 -2px 0 var(--accent); }}
nav button:focus-visible, select:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
iframe {{ display: block; width: 100%; height: 75vh; min-height: 360px; border: 1px solid var(--line); background: #ffffff; }}
.compare {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.compare > div {{ min-width: 0; display: flex; flex-direction: column; gap: 6px; }}
select {{ font: inherit; font-size: 13px; padding: 4px 6px; border: 1px solid var(--line); border-radius: 4px;
  background: var(--surface); color: var(--fg); max-width: 100%; }}
@media (max-width: 720px) {{ .compare {{ grid-template-columns: 1fr; }} }}
</style>
<header>
  <h1>{app_name}</h1>
  <span class="note">Mock data, not a live Tableau connection. Latest version: {latest_label}</span>
</header>
<nav id="tabs" aria-label="Versions">
{tab_buttons}
  <button type="button" data-tab="compare" aria-selected="false">Compare</button>
</nav>
{version_frames}
<section data-panel="compare" class="compare" hidden>
  <div><label for="compare-left" class="note">Left</label>
    <select id="compare-left">{left_options}</select>
    <iframe id="frame-left" title="Left version" src="{left_file}"></iframe></div>
  <div><label for="compare-right" class="note">Right</label>
    <select id="compare-right">{right_options}</select>
    <iframe id="frame-right" title="Right version" src="{right_file}"></iframe></div>
</section>
<script>
(function () {{
  // Show one panel (a version frame or the Compare view) and mark its tab.
  function show(name) {{
    document.querySelectorAll('[data-panel]').forEach(function (panel) {{ panel.hidden = panel.dataset.panel !== name; }});
    document.querySelectorAll('[data-tab]').forEach(function (tab) {{ tab.setAttribute('aria-selected', String(tab.dataset.tab === name)); }});
  }}
  document.getElementById('tabs').addEventListener('click', function (event) {{
    var tab = event.target.closest('[data-tab]');
    if (tab) {{ show(tab.dataset.tab); }}
  }});
  [['compare-left', 'frame-left'], ['compare-right', 'frame-right']].forEach(function (pair) {{
    document.getElementById(pair[0]).addEventListener('change', function (event) {{
      document.getElementById(pair[1]).src = event.target.value;
    }});
  }});
}})();
</script>
"""


def _options(versions: list, selected_file: str) -> str:
    """Build the <option> list of a Compare selector."""
    return "".join(
        f'<option value="{html.escape(v["file"])}"{" selected" if v["file"] == selected_file else ""}>'
        f'{index:02d} · {html.escape(v["label"])}</option>'
        for index, v in enumerate(versions, start=1))


def build_shell(workspace: Path) -> Path:
    """Write mock/preview.html with one tab per version and a Compare view.

    Args:
        workspace: The app workspace folder.

    Returns:
        Path of the shell page.

    Raises:
        ValueError: If mock/versions.json has no versions.
    """
    versions = _load_versions(workspace)
    if not versions:
        raise ValueError(f"No versions in {workspace / 'mock' / 'versions.json'}; run add_version first")
    latest = versions[-1]
    previous = versions[-2] if len(versions) > 1 else latest

    tab_buttons = "\n".join(
        f'  <button type="button" data-tab="{html.escape(v["file"])}" '
        f'aria-selected="{"true" if v is latest else "false"}">'
        f'<span class="num">{index:02d}</span>{html.escape(v["label"])}</button>'
        for index, v in enumerate(versions, start=1))
    version_frames = "\n".join(
        f'<iframe data-panel="{html.escape(v["file"])}" src="{html.escape(v["file"])}" '
        f'title="{html.escape(v["label"])}"{"" if v is latest else " hidden"}></iframe>'
        for v in versions)

    shell = SHELL_TEMPLATE.format(
        title=html.escape(f"{workspace.name} preview"),
        app_name=html.escape(workspace.name),
        latest_label=html.escape(latest["label"]),
        tab_buttons=tab_buttons,
        version_frames=version_frames,
        left_options=_options(versions, previous["file"]),
        right_options=_options(versions, latest["file"]),
        left_file=html.escape(previous["file"]),
        right_file=html.escape(latest["file"]))
    shell_path = workspace / "mock" / "preview.html"
    shell_path.write_text(shell, encoding="utf-8")
    logger.info(f"Wrote shell with {len(versions)} version(s): {shell_path}")
    return shell_path


def _setup_logging(workspace: Path) -> logging.FileHandler:
    """Log to stderr and to mock/logs/build_preview/build_preview.log.

    Args:
        workspace: The app workspace folder.

    Returns:
        The file handler, so the caller can close it.
    """
    log_dir = workspace / "mock" / "logs" / "build_preview"
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_dir / "build_preview.log", encoding="utf-8")
    stream_handler = logging.StreamHandler(sys.stderr)
    for handler in (file_handler, stream_handler):
        handler.setFormatter(formatter)
    logger.handlers = [file_handler, stream_handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return file_handler


def main(argv: list[str] | None = None) -> int:
    """Add one version and rebuild the shell page.

    Args:
        argv: Command-line arguments without the program name (default: sys.argv[1:]).

    Returns:
        0 on success, 1 on a build error.
    """
    parser = argparse.ArgumentParser(description="Build a mock preview of a Tableau data app.")
    parser.add_argument("workspace", type=Path, help="App workspace folder (holds the .twb and Packages/)")
    parser.add_argument("--label", required=True, help="Tab label of the new version")
    parser.add_argument("--mock", type=Path, help="mock-data.json (default: <workspace>/mock/mock-data.json)")
    parser.add_argument("--replace-last", action="store_true",
                        help="Rebuild the latest version under its number (only if it is not published yet)")
    args = parser.parse_args(argv)

    workspace = args.workspace.resolve()
    if not (workspace / "Packages").is_dir():
        # Check before logging setup: a mistyped path must not get a stray mock/logs/ folder.
        sys.stderr.write(f"Not an app workspace (no Packages folder): {workspace}\n")
        return 1
    file_handler = _setup_logging(workspace)
    try:
        logger.info("=== Script Started ===")
        add_version(workspace, args.mock or workspace / "mock" / "mock-data.json", args.label, args.replace_last)
        shell_path = build_shell(workspace)
        sys.stdout.write(f"{shell_path}\n")  # the only stdout output: the agent reads this path
        logger.info("=== Script Completed ===")
        return 0
    except (FileNotFoundError, ValueError) as error:  # json.JSONDecodeError is a ValueError
        logger.error(f"Build failed: {error}")
        return 1
    finally:
        file_handler.close()  # Windows keeps the log file locked until the handler closes


if __name__ == "__main__":
    sys.exit(main())
