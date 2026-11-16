// Applies a stored theme override before first paint. Storage can throw (private windows), so every access is guarded.
(function () {
  try {
    var t = localStorage.getItem("ask-hana-theme");
    if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
  } catch (e) { /* no stored preference */ }
})();
