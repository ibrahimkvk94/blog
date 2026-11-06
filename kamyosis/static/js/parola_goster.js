/* Parola alanlarına "göster / gizle" düğmesi (site ve yönetim paneli). İstenmeyen alanda: data-goster="yok". */
(function () {
  "use strict";
  var GOZ = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  var KAPALI = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M17.9 17.9A10.1 10.1 0 0 1 12 19C5 19 1 12 1 12a18.5 18.5 0 0 1 5.1-5.9M9.9 4.2A9.1 9.1 0 0 1 12 4c7 0 11 7 11 7a18.5 18.5 0 0 1-2.2 3.2M14.1 14.1a3 3 0 1 1-4.2-4.2M1 1l22 22"/></svg>';

  function yerlestir(input, dugme) {
    dugme.style.top = (input.offsetTop + input.offsetHeight / 2) + "px";
    dugme.style.left = (input.offsetLeft + input.offsetWidth - 34) + "px";
  }

  function ekle(input) {
    if (input.dataset.gosterEklendi || input.dataset.goster === "yok") return;
    input.dataset.gosterEklendi = "1";
    var kap = input.parentElement;
    if (window.getComputedStyle(kap).position === "static") kap.style.position = "relative";
    input.style.paddingRight = "2.4rem";
    var dugme = document.createElement("button");
    dugme.type = "button";
    dugme.className = "parola-goz";
    dugme.setAttribute("aria-label", "Parolayı göster");
    dugme.setAttribute("title", "Parolayı göster");
    dugme.innerHTML = GOZ;
    dugme.style.cssText = "position:absolute;transform:translateY(-50%);width:30px;height:30px;display:flex;" +
      "align-items:center;justify-content:center;border:0;background:transparent;color:#5b6b80;cursor:pointer;" +
      "padding:0;z-index:5;";
    dugme.addEventListener("click", function () {
      var acik = input.type === "password";
      input.type = acik ? "text" : "password";
      dugme.innerHTML = acik ? KAPALI : GOZ;
      dugme.setAttribute("aria-label", acik ? "Parolayı gizle" : "Parolayı göster");
      dugme.setAttribute("title", acik ? "Parolayı gizle" : "Parolayı göster");
      input.focus();
    });
    kap.appendChild(dugme);
    yerlestir(input, dugme);
    window.addEventListener("resize", function () { yerlestir(input, dugme); });
  }

  function hepsi() {
    Array.prototype.forEach.call(document.querySelectorAll('input[type="password"]'), ekle);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", hepsi);
  else hepsi();
  window.addEventListener("load", function () {  // yazı tipi yüklenince konum değişebilir
    Array.prototype.forEach.call(document.querySelectorAll(".parola-goz"), function (d) {
      var input = d.parentElement.querySelector('input[data-goster-eklendi]');
      if (input) yerlestir(input, d);
    });
  });
})();
