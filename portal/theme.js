(function () {
  var theme = 'dark';
  try {
    var saved = localStorage.getItem('cortexdev-theme');
    if (saved === 'light' || saved === 'dark') theme = saved;
  } catch (e) {}
  document.documentElement.setAttribute('data-theme', theme);
})();
