/*
 * Fake Tableau Extensions API for a data app preview.
 *
 * Replaces tableau.extensions.1.latest.min.js in a preview page. It serves the
 * datasource, metadata and query rows from window.__DATA_APP_MOCK__, which the
 * preview builder sets before this script. Shape of the mock:
 *   { datasource: { id, name }, metadata: [...], queries: [ { query, data } ] }
 * A query matches when it is deep-equal to a mock query (object key order does
 * not count; array order counts).
 */
(function () {
  'use strict';

  // JSON with sorted object keys at every level, so key order never matters.
  // Keys with an undefined value are skipped, as JSON.stringify does.
  function canonicalJson(value) {
    if (Array.isArray(value)) {
      return '[' + value.map(canonicalJson).join(',') + ']';
    }
    if (value && typeof value === 'object') {
      return '{' + Object.keys(value).filter(function (key) {
        return value[key] !== undefined;
      }).sort().map(function (key) {
        return JSON.stringify(key) + ':' + canonicalJson(value[key]);
      }).join(',') + '}';
    }
    return JSON.stringify(value);
  }

  // The mock is read on each call, so a missing mock fails with a clear message.
  function getMock() {
    var mock = window.__DATA_APP_MOCK__;
    if (!mock) {
      return Promise.reject(new Error('No mock data: window.__DATA_APP_MOCK__ is not set'));
    }
    return Promise.resolve(mock);
  }

  function buildDataSource(mock) {
    var rowsByQuery = {};
    (mock.queries || []).forEach(function (entry) {
      rowsByQuery[canonicalJson(entry.query)] = entry.data;
    });
    return {
      id: mock.datasource.id,
      name: mock.datasource.name,
      readMetadataAsync: function () {
        return Promise.resolve({ data: mock.metadata || [] });
      },
      queryAsync: function (query) {
        var key = canonicalJson(query);
        if (!Object.prototype.hasOwnProperty.call(rowsByQuery, key)) {
          // The app shows this message, so the model knows which query to capture.
          return Promise.reject(new Error('No mock rows for query: ' + key));
        }
        return Promise.resolve({ data: rowsByQuery[key] });
      }
    };
  }

  function getDataSourcesAsync() {
    return getMock().then(function (mock) { return [buildDataSource(mock)]; });
  }

  window.tableau = {
    extensions: {
      initializeAsync: function () {
        return getMock().then(function () { return undefined; });
      },
      workbook: { getAllDataSourcesAsync: getDataSourcesAsync },
      worksheetContent: { worksheet: { getDataSourcesAsync: getDataSourcesAsync } }
    }
  };
})();
