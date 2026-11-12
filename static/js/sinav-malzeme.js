/* Sınav malzemeleri: süzgeçler (program, dersi veren bölüm, sınıf, durum, arama) ve satır başına anında kayıt. */
(function () {
  "use strict";
  var sayfa = document.getElementById("mzSayfa");
  if (!sayfa) return;
  var ANAHTAR = "kamyosis.sinavMalzeme";
  var durum = { p: "", d: "", s: "", g: "", benim: false, q: "" };
  var kayitli = null;
  try { kayitli = JSON.parse(localStorage.getItem(ANAHTAR) || "null"); } catch (e) { /* yok */ }
  if (kayitli) Object.assign(durum, kayitli, { q: "" });
  else if (sayfa.dataset.benim) {  // ilk açılış: kendi bölümü
    if (sayfa.dataset.benimProgram) durum.p = sayfa.dataset.benim; else durum.d = sayfa.dataset.benim;
  }
  var adres = new URLSearchParams(location.search);
  if (adres.has("program")) durum.p = adres.get("program");

  var satirlar = Array.prototype.slice.call(sayfa.querySelectorAll("tbody tr"));
  var cipler = sayfa.querySelectorAll("[data-program]:not(tr)");
  var dersSec = document.getElementById("mzDersBolum");
  var benimKutu = document.getElementById("mzBenim");
  var ara = document.getElementById("mzAra");
  var csrf = sayfa.querySelector("[name=csrfmiddlewaretoken]").value;
  var programVar = Array.prototype.some.call(cipler, function (c) { return c.dataset.program === durum.p; });
  if (!programVar) durum.p = "";
  if (!Array.prototype.some.call(dersSec.options, function (o) { return o.value === durum.d; })) durum.d = "";

  // Aynı dersin birden çok girilebilir programı varsa "tümüne uygula" düğmesi görünür
  var kodSayisi = {};
  satirlar.forEach(function (tr) { if (tr.dataset.girebilir === "1") kodSayisi[tr.dataset.kod] = (kodSayisi[tr.dataset.kod] || 0) + 1; });

  function kaydetSecim() {
    try { localStorage.setItem(ANAHTAR, JSON.stringify({ p: durum.p, d: durum.d, s: durum.s, g: durum.g, benim: durum.benim })); } catch (e) { /* yok */ }
  }
  function kucuk(m) { return (m || "").toLocaleLowerCase("tr"); }

  function uygula() {
    var q = kucuk(durum.q.trim()), n = 0, girilen = 0;
    cipler.forEach(function (c) { c.classList.toggle("secili", c.dataset.program === durum.p); });
    sayfa.querySelectorAll("[data-program-sec]").forEach(function (c) { c.classList.toggle("secili", c.dataset.programSec === durum.p); });
    sayfa.querySelectorAll("[data-sinif-sec]").forEach(function (b) { b.classList.toggle("active", b.dataset.sinifSec === durum.s); });
    sayfa.querySelectorAll("[data-durum]").forEach(function (b) { b.classList.toggle("active", b.dataset.durum === durum.g); });
    dersSec.value = durum.d;
    if (benimKutu) benimKutu.checked = durum.benim;
    satirlar.forEach(function (tr) {
      var uy = (!durum.p || tr.dataset.program === durum.p) && (!durum.d || tr.dataset.dersBolum === durum.d) &&
               (!durum.s || tr.dataset.sinif === durum.s) && (!durum.g || tr.dataset.girildi === durum.g) &&
               (!durum.benim || tr.dataset.girebilir === "1") && (!q || kucuk(tr.dataset.ara).indexOf(q) >= 0);
      tr.hidden = !uy;
      if (uy) { n++; if (tr.dataset.girildi === "1") girilen++; }
    });
    document.getElementById("mzBos").hidden = n > 0;
    var parca = [];
    if (durum.p) parca.push("Program <b>" + durum.p + "</b>");
    if (durum.d) parca.push("Dersi veren <b>" + dersSec.options[dersSec.selectedIndex].text + "</b>");
    if (durum.s) parca.push("<b>" + durum.s + ". sınıf</b>");
    if (durum.g) parca.push(durum.g === "1" ? "girilmiş" : "girilmemiş");
    if (durum.benim) parca.push("girebileceklerim");
    if (q) parca.push("“" + durum.q.replace(/[<>&"]/g, "") + "”");
    document.getElementById("mzSonuc").innerHTML = (parca.length ? parca.join(" · ") + " — " : "") + n + " satır, " + girilen +
      " girilmiş" + (parca.length ? ' · <a href="#" id="mzTemizle">süzgeci temizle</a>' : "");
    var t = document.getElementById("mzTemizle");
    if (t) t.addEventListener("click", function (e) {
      e.preventDefault(); durum = { p: "", d: "", s: "", g: "", benim: false, q: "" }; ara.value = ""; kaydetSecim(); uygula();
    });
    document.getElementById("mzExcel").href = sayfa.dataset.excel + (durum.p ? "?program=" + encodeURIComponent(durum.p) : "");
  }

  function ilerleme() {
    var say = {}, toplam = 0;
    satirlar.forEach(function (tr) { if (tr.dataset.girildi === "1") { say[tr.dataset.program] = (say[tr.dataset.program] || 0) + 1; toplam++; } });
    sayfa.querySelectorAll("[data-ilerleme]").forEach(function (el) {
      var g = say[el.dataset.ilerleme] || 0, t = +el.dataset.toplam;
      el.textContent = g + "/" + t;
      el.parentNode.querySelector(".mz-bar i").style.width = (t ? Math.round(100 * g / t) : 0) + "%";
      el.parentNode.classList.toggle("tamam", g === t);
    });
    document.getElementById("mzToplam").textContent = toplam + "/" + satirlar.length;
  }

  function goster(tr, s) {
    tr.querySelectorAll(".mz-sec").forEach(function (b) {
      var on = b.dataset.s === "yok" ? s.yok : s.secimler.indexOf(b.dataset.s) >= 0;
      b.classList.toggle("secili", on); b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    var d = tr.querySelector(".mz-diger");
    if (d && document.activeElement !== d) d.value = s.diger;
    tr.dataset.girildi = s.metin ? "1" : "0";
  }

  function oku(tr) {
    var secimler = [];
    tr.querySelectorAll(".mz-sec.secili").forEach(function (b) { if (b.dataset.s !== "yok") secimler.push(b.dataset.s); });
    return { kod: tr.dataset.kod, bolum: tr.dataset.program, secimler: secimler, diger: tr.querySelector(".mz-diger").value,
             yok: !!tr.querySelector(".mz-yok.secili") };
  }

  function kaydet(tr, hepsi) {
    var veri = oku(tr), d = tr.querySelector(".mz-durum");
    veri.hepsi = !!hepsi;
    d.className = "mz-durum bekliyor"; d.innerHTML = '<i class="bi bi-arrow-repeat"></i>';
    fetch(sayfa.dataset.kaydet, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(veri), credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.hata || "Kaydedilemedi"); return j; }); })
      .then(function (j) {
        j.satirlar.forEach(function (s) {
          satirlar.forEach(function (x) {
            if (x.dataset.kod === tr.dataset.kod && x.dataset.program === s.bolum) {
              goster(x, s);
              var xd = x.querySelector(".mz-durum");
              if (xd) { xd.className = "mz-durum tamam"; xd.innerHTML = '<i class="bi bi-check-lg"></i>'; xd.title = "Kaydedildi"; }
            }
          });
        });
        ilerleme();
      })
      .catch(function (e) { d.className = "mz-durum hata"; d.innerHTML = '<i class="bi bi-exclamation-circle"></i>'; d.title = e.message; });
  }

  satirlar.forEach(function (tr) {
    if (tr.dataset.girebilir !== "1") return;
    var hepsiBtn = tr.querySelector(".mz-hepsi");
    if (kodSayisi[tr.dataset.kod] > 1) hepsiBtn.hidden = false;
    hepsiBtn.addEventListener("click", function () { kaydet(tr, true); });
    tr.querySelectorAll(".mz-sec").forEach(function (b) {
      b.addEventListener("click", function () {
        var on = !b.classList.contains("secili");
        if (b.dataset.s === "yok" && on) {  // "Yok" diğerlerini kaldırır
          tr.querySelectorAll(".mz-sec").forEach(function (x) { x.classList.remove("secili"); });
          tr.querySelector(".mz-diger").value = "";
        } else if (on) tr.querySelector(".mz-yok").classList.remove("secili");
        b.classList.toggle("secili", on);
        kaydet(tr);
      });
    });
    var diger = tr.querySelector(".mz-diger"), zaman = null;
    diger.addEventListener("input", function () {
      if (diger.value.trim()) tr.querySelector(".mz-yok").classList.remove("secili");
      clearTimeout(zaman); zaman = setTimeout(function () { kaydet(tr); }, 700);
    });
    diger.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); clearTimeout(zaman); kaydet(tr); } });
  });

  cipler.forEach(function (c) { c.addEventListener("click", function () { durum.p = durum.p === c.dataset.program ? "" : c.dataset.program; kaydetSecim(); uygula(); }); });
  sayfa.querySelectorAll("[data-program-sec]").forEach(function (c) {
    c.addEventListener("click", function () { durum.p = durum.p === c.dataset.programSec ? "" : c.dataset.programSec; kaydetSecim(); uygula(); });
  });
  dersSec.addEventListener("change", function () { durum.d = dersSec.value; kaydetSecim(); uygula(); });
  sayfa.querySelectorAll("[data-sinif-sec]").forEach(function (b) { b.addEventListener("click", function () { durum.s = b.dataset.sinifSec; kaydetSecim(); uygula(); }); });
  sayfa.querySelectorAll("[data-durum]").forEach(function (b) { b.addEventListener("click", function () { durum.g = b.dataset.durum; kaydetSecim(); uygula(); }); });
  if (benimKutu) benimKutu.addEventListener("change", function () { durum.benim = benimKutu.checked; kaydetSecim(); uygula(); });
  ara.addEventListener("input", function () { durum.q = ara.value; uygula(); });
  ilerleme();
  uygula();
})();
