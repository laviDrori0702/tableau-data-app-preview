// Fake vendored chart library. The string below must not close the inline <script>.
window.chartLib = { closingTag: "</script>", renderList: function (root, items) {
  items.forEach(function (text) { var li = document.createElement('li'); li.textContent = text; root.appendChild(li); });
} };
