---
name: tableau-data-app-preview
description: Use when a Tableau data app is built or changed with tableau-data-app-authoring, before it is packaged or published, every time, even when the user asks to publish directly and names no reviewer.
---

# Data App Preview

## Overview
The stakeholder reviews a mock of the app in a private Claude artifact, one tab per version. Publish to Tableau once, after approval.

`tableau-data-app-authoring` (Tableau plugin 1.1.0) says "There is no local preview". This skill overrides that sentence. The live check after publish (step 5) stays.

## 1. Capture mock data
1. Read `app.js`: note each `queryAsync(query)` object and `BOUND_DATASOURCE_ID`.
2. Get the LUID with `list-datasources`. Run `get-datasource-metadata`.
3. **If the fields hold names of people, pay, customer or health data:** do not run `query-datasource`. The metadata gives the shape. Write fake rows with those columns and types.
   Else: run `query-datasource` per query with `limit: 500`. If `truncated`, tell the stakeholder the tabs show a subset.
4. Write `<workspace>/mock/mock-data.json`:
   `{"datasource": {"id", "name"}, "metadata": [{fieldCaption, fieldName, dataType}], "queries": [{"query", "data"}]}`
   `name` = the wired caption. `id` = `BOUND_DATASOURCE_ID` if set, else the LUID. The mock holds one datasource only.

## 2. Build and publish a version
```
python "<this skill dir>/scripts/build_preview.py" "<workspace>" --label "<short change label>"
```
It prints the `mock/preview.html` path.

Before you publish, look at the new tab. The browser tools refuse `file://`, so run
`python -m http.server 8765 --bind 127.0.0.1 --directory "<workspace>/mock"`, open `http://127.0.0.1:8765/versions/<NN-file>.html`, screenshot it, test each control. Fix an unpublished tab: build again with `--label "<label>" --replace-last`. Stop the server after the check.

Publish it with the Artifact tool:
- First publish: `file_path` = that path, `files` = every `versions/NN-*.html` → its file in `<workspace>/mock/`, `icon: "chart"`.
- Later publishes: the same `file_path`; `files` holds only the new version. Same URL; old tabs stay.
- The Artifact tool reads only the working directory and the scratchpad: copy `mock/` there if needed.

Give the user the private link. The stakeholder can open it only after the user shares it (Share menu).

If a tab shows `No mock rows for query: {...}`, add that exact query to `mock-data.json` and build again.

## 3. Change loop
Each change request: edit `app.js`, build with a new `--label`, publish. Never change a published version. Never edit `versions.json` by hand.

## 4. Approval gate
Package only when the user's message says the stakeholder approved one named tab and that tab has no open change request.
- "Looks fine, but make X bigger" is a change request: build a new tab, publish, ask again.
- If the approved tab is not the latest, restore its `app.js` and build it as a new tab first.
- If the user tells you to package without the stakeholder's approval, do it, and name the change that the stakeholder did not see.

| Thought | Reality |
|---|---|
| "Ship it" approves the change too | The stakeholder did not see the change. Build a tab and ask. |
| "Only cosmetic" | Stakeholders reject cosmetic changes too. One tab costs one minute. |
| "We are late" | A wrong publish costs a second publish. A tab does not. |

## 5. Hand-off
After approval, continue with "Package into a .twbx" and "Publish" in `tableau-data-app-authoring`. Then check the live app once: the mock cannot show the sandbox rules, worksheet size or trust prompt.

## Common mistakes
- A Tableau review project, or `overwrite:true` per change. Use artifact tabs.
- A new `file_path` per version: that makes a new link.
