(function () {
  'use strict';
  // Fixture app: the template boot flow with one authored queryAsync call.
  var root = document.getElementById('app');
  tableau.extensions.initializeAsync().then(function () {
    return tableau.extensions.workbook.getAllDataSourcesAsync();
  }).then(function (list) {
    var ds = list[0];
    return ds.queryAsync({ fields: [{ fieldCaption: 'Category' }] });
  }).then(function (result) {
    var heading = document.createElement('h1');
    heading.textContent = 'מכירות';
    root.appendChild(heading);
    var list = document.createElement('ul');
    root.appendChild(list);
    window.chartLib.renderList(list, result.data.map(function (row) { return row.Category; }));
  }).catch(function (err) {
    root.textContent = 'Live query unavailable: ' + err.message;
  });
})();
