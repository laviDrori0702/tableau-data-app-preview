# tableau-data-app-preview

A Claude Code skill. It shows a Tableau data app to a stakeholder before it goes to Tableau.

Claude builds a mock of the app and publishes it as a private Claude artifact. Each change adds one tab, so the stakeholder can compare versions. Claude packages and publishes to Tableau only after the stakeholder approves one tab.

## Why use it
The Tableau plugin skill `tableau-data-app-authoring` has no preview. It publishes, and the review happens live in Tableau. With that flow, each small change is one more publish to the server. Also, an agent can read "looks fine, but make X bigger" as an approval.

This skill adds a review loop that costs no Tableau publish.

## Requirements
- Claude Code with the Tableau plugin (`tableau-data-app-authoring`, plus the Tableau MCP tools `list-datasources`, `get-datasource-metadata`, `query-datasource`).
- Python 3.9 or later. The script uses only the standard library.
- The Artifact tool, to publish the preview page on claude.ai.

## Install
The skill goes in your user-level skills folder, `~/.claude/skills/`. Claude Code then loads it in each project.

### 1. Check the prerequisites
**Windows (PowerShell)**
```powershell
git --version
python --version
```

**macOS (Terminal)**
```bash
git --version
python3 --version
```
Each command must print a version. Python must be 3.9 or later.

### 2. Clone the skill
**Windows (PowerShell)**
```powershell
git clone https://github.com/laviDrori0702/tableau-data-app-preview.git "$HOME\.claude\skills\tableau-data-app-preview"
```

**macOS (Terminal)**
```bash
git clone https://github.com/laviDrori0702/tableau-data-app-preview.git ~/.claude/skills/tableau-data-app-preview
```
`git clone` makes the `skills` folder if it does not exist.

### 3. Verify the install
**Windows (PowerShell)**
```powershell
Test-Path "$HOME\.claude\skills\tableau-data-app-preview\SKILL.md"
```

**macOS (Terminal)**
```bash
test -f ~/.claude/skills/tableau-data-app-preview/SKILL.md && echo True
```
Expected output: `True`.

### 4. Start Claude Code
Start a new Claude Code session. Claude starts the skill when it builds or changes a data app. You can also ask: "Preview the data app before you publish."

### Update
**Windows (PowerShell)**
```powershell
git -C "$HOME\.claude\skills\tableau-data-app-preview" pull
```

**macOS (Terminal)**
```bash
git -C ~/.claude/skills/tableau-data-app-preview pull
```

### Uninstall
**Windows (PowerShell)**
```powershell
Remove-Item -Recurse -Force "$HOME\.claude\skills\tableau-data-app-preview"
```

**macOS (Terminal)**
```bash
rm -rf ~/.claude/skills/tableau-data-app-preview
```

## How it works
1. Claude reads the queries in `app.js` and gets the datasource metadata. It then writes `<workspace>/mock/mock-data.json`. For personal data (names, pay, customer or health data) it writes fake rows and does not query the real rows.
2. `scripts/build_preview.py` makes one HTML page from `content/index.html`. It puts all local CSS and JS into the page. It also replaces the Tableau Extensions API with `assets/tableau-stub.js`, which serves the mock rows.
3. Claude publishes `mock/preview.html` as an artifact: one tab per version, plus a Compare view.
4. You share the artifact link with the stakeholder (Share menu). Each change request makes a new tab. Published tabs do not change.
5. After the stakeholder approves a tab, Claude packages the `.twbx` and publishes it with `tableau-data-app-authoring`.

## Files
| File | Purpose |
|---|---|
| `SKILL.md` | The instructions that Claude follows. |
| `scripts/build_preview.py` | Builds one version page and the tab page (`mock/preview.html`). |
| `assets/tableau-stub.js` | A fake Tableau Extensions API that reads the mock data. |

The script writes only into `<workspace>/mock/`. `package_twbx.py` does not pack that folder.

## Tests
Run the tests from the skill folder. They need `pytest` and Node.js 18 or later.
```
python -m pytest scripts/tests -q
node scripts/tests/test_tableau_stub.mjs
```
One test packages a sample app with the Tableau plugin's `package_twbx.py`. If the plugin is not installed, pytest skips that test.

To run the tests before each commit, enable the hook once per clone:
```
git config core.hooksPath .githooks
```

## Limits
- **Mock data only.** The preview does not show the Tableau sandbox rules, the worksheet size, or the trust prompt. Claude checks the live app once after publish.
- **The stub mocks only these calls:** `initializeAsync`, `workbook.getAllDataSourcesAsync`, `worksheetContent.worksheet.getDataSourcesAsync`, `readMetadataAsync` and `queryAsync`. Calls such as `settings`, `getSummaryDataAsync` and worksheet events are not mocked.
- **Exact query match.** The stub returns rows only for a query that is the same JSON as a query in `mock-data.json`. Object key order does not matter; array order does. If a control changes the query (for example a filter), each state needs its own entry. A missing query shows `No mock rows for query: {...}` in the tab.
- **One datasource.** The mock holds one datasource. The stub returns it with `id` and `name` from `mock-data.json`, so the app can find it by `BOUND_DATASOURCE_ID` (the scaffold default), by caption, or as the first datasource.
- **16 MB per page.** This is the artifact limit. The script stops if a version page is larger.
