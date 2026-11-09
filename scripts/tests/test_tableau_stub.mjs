// Tests for skills/tableau-data-app-preview/assets/tableau-stub.js.
// The stub is a plain browser script, so each test loads it into this process with vm.
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const stubPath = fileURLToPath(new URL('../../assets/tableau-stub.js', import.meta.url));
const mockPath = fileURLToPath(new URL('./fixtures/mock-data.json', import.meta.url));
const mock = JSON.parse(fs.readFileSync(mockPath, 'utf8'));

// Load the stub the way a browser does: as a classic script with window as the global.
function loadStub() {
  delete globalThis.tableau;
  vm.runInThisContext(fs.readFileSync(stubPath, 'utf8'), { filename: stubPath });
}

let ds;
beforeEach(async () => {
  globalThis.window = globalThis;
  window.__DATA_APP_MOCK__ = structuredClone(mock);
  loadStub();
  await tableau.extensions.initializeAsync();
  [ds] = await tableau.extensions.workbook.getAllDataSourcesAsync();
});

test('datasource from workbook list', async () => {
  assert.equal(ds.id, mock.datasource.id);
  assert.equal(ds.name, mock.datasource.name);
});

test('metadata', async () => {
  assert.deepEqual((await ds.readMetadataAsync()).data, mock.metadata);
});

test('query match ignores key order', async () => {
  const query = { fields: [{ function: 'SUM', fieldCaption: 'Sales' }] }; // keys reversed vs fixture
  assert.deepEqual((await ds.queryAsync(query)).data, mock.queries[1].data);
});

test('undefined values are ignored when matching', async () => {
  const query = { fields: [{ fieldCaption: 'Category', function: undefined }] };
  assert.deepEqual((await ds.queryAsync(query)).data, mock.queries[0].data);
});

test('unknown query rejects with query json', async () => {
  await assert.rejects(ds.queryAsync({ fields: [{ fieldCaption: 'Nope' }] }),
    { message: 'No mock rows for query: {"fields":[{"fieldCaption":"Nope"}]}' });
});

test('worksheet fallback returns same datasource', async () => {
  const [worksheetDs] = await tableau.extensions.worksheetContent.worksheet.getDataSourcesAsync();
  assert.equal(worksheetDs.id, mock.datasource.id);
});

test('missing mock fails on initializeAsync', async () => {
  delete window.__DATA_APP_MOCK__;
  loadStub();
  await assert.rejects(tableau.extensions.initializeAsync(),
    { message: 'No mock data: window.__DATA_APP_MOCK__ is not set' });
});
