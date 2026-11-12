/* Sınav takvimi: program / sınıf / arama süzgeci ve görünüm (günler ↔ program tablosu). Seçim tarayıcıda hatırlanır. */
(function () {
  "use strict";
  var sayfa = document.getElementById("stSayfa");
  if (!sayfa) return;
  var ANAHTAR = "kamyosis.sinavTakvimi";
  var durum = { p: "", s: "", q: "", v: "gunler" };
  try { Object.assign(durum, JSON.parse(localStorage.getItem(ANAHTAR) || "{}"), { q: "" }); } catch (e) { /* yok */ }
  var adres = new URLSearchParams(location.search);
  if (adres.has("program")) durum.p = adres.get("program");
  if (adres.has("sinif")) durum.s = adres.get("sinif");

  var cipler = sayfa.querySelectorAll("[data-program]");
  var programlar = Array.prototype.map.call(cipler, function (c) { return c.dataset.program; });
  if (programlar.indexOf(durum.p) < 0) durum.p = "";
  var benim = sayfa.dataset.benim;
  if (benim) cipler.forEach(function (c) { if (c.dataset.program === benim) { c.classList.add("benim"); c.title += " (bölümünüz)"; } });

  function kaydet() {
    try { localStorage.setItem(ANAHTAR, JSON.stringify({ p: durum.p, s: durum.s, v: durum.v })); } catch (e) { /* yok */ }
  }

  function kucuk(m) { return (m || "").toLocaleLowerCase("tr"); }

  function uygula() {
    var q = kucuk(durum.q.trim());
    cipler.forEach(function (c) { c.classList.toggle("secili", c.dataset.program === durum.p); });
    sayfa.querySelectorAll("[data-sinif]").forEach(function (b) {
      if (b.tagName === "BUTTON") b.classList.toggle("active", b.dataset.sinif === durum.s);
    });
    sayfa.querySelectorAll("[data-gorunum]").forEach(function (b) { b.classList.toggle("active", b.dataset.gorunum === durum.v); });

    var toplam = 0;
    sayfa.querySelectorAll("[data-gun]").forEach(function (gun) {
      var gunSayi = 0;
      gun.querySelectorAll("[data-oturum]").forEach(function (ot) {
        var n = 0;
        ot.querySelectorAll(".st-kart").forEach(function (k) {
          var uy = (!durum.p || k.dataset.bolumler.indexOf(" " + durum.p + " ") >= 0) &&
                   (!durum.s || k.dataset.sinif === durum.s) &&
                   (!q || kucuk(k.dataset.ara).indexOf(q) >= 0);
          k.hidden = !uy;
          if (uy) n++;
          k.querySelectorAll(".st-progs span").forEach(function (s) { s.classList.toggle("secili", s.dataset.p === durum.p); });
        });
        ot.querySelector(".st-kartlar").hidden = n === 0;
        ot.querySelector(".st-yok").hidden = n > 0;
        ot.classList.toggle("bos", n === 0);
        gunSayi += n;
      });
      gun.hidden = gunSayi === 0;
      var say = gun.querySelector("[data-gun-sayi]");
      if (say) say.textContent = gunSayi;
      toplam += gunSayi;
    });

    var satir = 0;
    sayfa.querySelectorAll("#stTablo tbody tr").forEach(function (tr) {
      var uy = (!durum.p || tr.dataset.bolum === durum.p) && (!durum.s || tr.dataset.sinif === durum.s);
      tr.hidden = !uy;
      if (uy) satir++;
      tr.querySelectorAll(".st-hucre").forEach(function (h) { h.classList.toggle("soluk", !!q && kucuk(h.dataset.ara).indexOf(q) < 0); });
    });

    var tablo = durum.v === "tablo";
    document.getElementById("stGunler").hidden = tablo;
    document.getElementById("stTablo").hidden = !tablo;
    document.getElementById("stBos").hidden = tablo ? satir > 0 : toplam > 0;

    var parca = [];
    if (durum.p) {
      var cip = sayfa.querySelector('[data-program="' + durum.p + '"]');
      parca.push("<b>" + durum.p + "</b> " + (cip ? cip.title.replace(" (bölümünüz)", "") : ""));
    }
    if (durum.s) parca.push("<b>" + durum.s + ". sınıf</b>");
    if (q) parca.push("“" + durum.q.replace(/[<>&"]/g, "") + "”");
    document.getElementById("stSonuc").innerHTML = parca.length
      ? parca.join(" · ") + (tablo ? "" : " — " + toplam + " sınav") + ' · <a href="#" id="stTemizle">süzgeci temizle</a>'
      : "";
    var temizle = document.getElementById("stTemizle");
    if (temizle) temizle.addEventListener("click", function (e) {
      e.preventDefault(); durum.p = ""; durum.s = ""; durum.q = ""; document.getElementById("stAra").value = ""; kaydet(); uygula();
    });
  }

  cipler.forEach(function (c) {
    c.addEventListener("click", function () { durum.p = durum.p === c.dataset.program ? "" : c.dataset.program; kaydet(); uygula(); });
  });
  sayfa.querySelectorAll("button[data-sinif]").forEach(function (b) {
    b.addEventListener("click", function () { durum.s = b.dataset.sinif; kaydet(); uygula(); });
  });
  sayfa.querySelectorAll("[data-gorunum]").forEach(function (b) {
    b.addEventListener("click", function () { durum.v = b.dataset.gorunum; kaydet(); uygula(); });
  });
  var ara = document.getElementById("stAra");
  ara.addEventListener("input", function () { durum.q = ara.value; uygula(); });
  uygula();
})();
