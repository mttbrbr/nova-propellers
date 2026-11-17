// NOVA: in the dark theme the manual's figures use the recoloured copy in _static/figure-scuro;
// in the light theme they go back to the original. Follows theme changes.
(function () {
  function aggiorna() {
    var scuro = document.documentElement.classList.contains("dark");
    document.querySelectorAll('figure img[src$=".svg"], figure img[data-nova-chiaro]').forEach(function (img) {
      var chiaro = img.getAttribute("data-nova-chiaro");
      if (!chiaro) {
        if (img.getAttribute("src").indexOf("_images/") < 0) return;
        chiaro = img.getAttribute("src");
        img.setAttribute("data-nova-chiaro", chiaro);
      }
      var voluto = scuro ? chiaro.replace("_images/", "_static/figure-scuro/") : chiaro;
      if (img.getAttribute("src") !== voluto) img.setAttribute("src", voluto);
    });
  }
  // Left-menu groups (USER GUIDE, TECHNICAL MANUAL) can be opened and closed: the group of the
  // current page stays open, the others as the reader left them (all open at first).
  function gruppi() {
    var chiave = function (c) { return "nova-gruppo:" + c.textContent.trim(); };
    document.querySelectorAll(".globaltoc > p.caption").forEach(function (c) {
      var lista = c.nextElementSibling;
      if (!lista || lista.tagName !== "UL") return;
      c.classList.add("nova-gruppo");
      c.setAttribute("tabindex", "0");
      var corrente = !!lista.querySelector(".current");
      var chiuso = false;
      try { chiuso = localStorage.getItem(chiave(c)) === "chiuso"; } catch (e) {}
      if (chiuso && !corrente) c.classList.add("nova-chiuso");
      c.setAttribute("aria-expanded", c.classList.contains("nova-chiuso") ? "false" : "true");
      var cambia = function () {
        var ora = c.classList.toggle("nova-chiuso");
        c.setAttribute("aria-expanded", ora ? "false" : "true");
        try { localStorage.setItem(chiave(c), ora ? "chiuso" : "aperto"); } catch (e) {}
      };
      c.addEventListener("click", cambia);
      c.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); cambia(); }
      });
    });
  }
  document.addEventListener("DOMContentLoaded", function () {
    gruppi();
    aggiorna();
    new MutationObserver(aggiorna).observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  });
})();
