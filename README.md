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
Copy this folder to `~/.claude/skills/tableau-data-app-preview/`. On Windows, that is `C:\Users\<you>\.claude\skills\tableau-data-app-preview\`. Then start a new Claude Code session.

Claude starts the skill when it builds or changes a data app. You can also ask: "Preview the data app before you publish."

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

## Limits
- **Mock data only.** The preview does not show the Tableau sandbox rules, the worksheet size, or the trust prompt. Claude checks the live app once after publish.
- **The stub mocks only these calls:** `initializeAsync`, `workbook.getAllDataSourcesAsync`, `worksheetContent.worksheet.getDataSourcesAsync`, `readMetadataAsync` and `queryAsync`. Calls such as `settings`, `getSummaryDataAsync` and worksheet events are not mocked.
- **Exact query match.** The stub returns rows only for a query that is the same JSON as a query in `mock-data.json`. Object key order does not matter; array order does. If a control changes the query (for example a filter), each state needs its own entry. A missing query shows `No mock rows for query: {...}` in the tab.
- **One datasource.** The mock holds one datasource. The stub returns it with `id` and `name` from `mock-data.json`, so the app can find it by `BOUND_DATASOURCE_ID` (the scaffold default), by caption, or as the first datasource.
- **16 MB per page.** This is the artifact limit. The script stops if a version page is larger.
