// MetiX: nel tema scuro le figure del manuale usano la copia ricolorata in _static/figure-scuro
// (prodotta da `make figure`); nel tema chiaro tornano all'originale. Segue il cambio di tema.
(function () {
  function aggiorna() {
    var scuro = document.documentElement.classList.contains("dark");
    document.querySelectorAll('figure img[src$=".svg"], figure img[data-metix-chiaro]').forEach(function (img) {
      var chiaro = img.getAttribute("data-metix-chiaro");
      if (!chiaro) {
        if (img.getAttribute("src").indexOf("_images/") < 0) return;
        chiaro = img.getAttribute("src");
        img.setAttribute("data-metix-chiaro", chiaro);
      }
      var voluto = scuro ? chiaro.replace("_images/", "_static/figure-scuro/") : chiaro;
      if (img.getAttribute("src") !== voluto) img.setAttribute("src", voluto);
    });
  }
  // Gruppi del menu a sinistra (MANUALE TECNICO, USO, SVILUPPO) apribili e chiudibili: aperto
  // quello della pagina corrente, gli altri come li ha lasciati il lettore (tutti aperti all'inizio).
  function gruppi() {
    var chiave = function (c) { return "metix-gruppo:" + c.textContent.trim(); };
    document.querySelectorAll(".globaltoc > p.caption").forEach(function (c) {
      var lista = c.nextElementSibling;
      if (!lista || lista.tagName !== "UL") return;
      c.classList.add("metix-gruppo");
      c.setAttribute("tabindex", "0");
      var corrente = !!lista.querySelector(".current");
      var chiuso = false;
      try { chiuso = localStorage.getItem(chiave(c)) === "chiuso"; } catch (e) {}
      if (chiuso && !corrente) c.classList.add("metix-chiuso");
      c.setAttribute("aria-expanded", c.classList.contains("metix-chiuso") ? "false" : "true");
      var cambia = function () {
        var ora = c.classList.toggle("metix-chiuso");
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
