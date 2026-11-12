/* Etüt görevlendirmeleri: süzgeçler, aranabilir öğretim elemanı seçici ve satır başına anında kayıt. */
(function () {
  "use strict";
  var sayfa = document.getElementById("etSayfa");
  if (!sayfa) return;
  var ANAHTAR = "kamyosis.sinavEtut";
  var durum = { p: "", d: "", s: "", g: "", gun: "", benim: false, q: "" };
  var kayitli = null;
  try { kayitli = JSON.parse(localStorage.getItem(ANAHTAR) || "null"); } catch (e) { /* yok */ }
  if (kayitli) Object.assign(durum, kayitli, { q: "" });
  else if (sayfa.dataset.benim) {
    if (sayfa.dataset.benimProgram) durum.p = sayfa.dataset.benim; else durum.d = sayfa.dataset.benim;
  }
  var adaylar = JSON.parse(document.getElementById("etAdaylar").textContent || "[]");
  var satirlar = Array.prototype.slice.call(sayfa.querySelectorAll("tbody tr"));
  var cipler = sayfa.querySelectorAll("button[data-program]");
  var dersSec = document.getElementById("etDersBolum");
  var benimKutu = document.getElementById("etBenim");
  var ara = document.getElementById("etAra");
  var liste = document.getElementById("etListe");
  var csrf = sayfa.querySelector("[name=csrfmiddlewaretoken]").value;
  function kucuk(m) { return (m || "").toLocaleLowerCase("tr"); }
  function var_mi(sec, deger) { return Array.prototype.some.call(sec, function (x) { return (x.dataset ? x.dataset.program : x.value) === deger; }); }
  if (!var_mi(cipler, durum.p)) durum.p = "";
  if (!var_mi(dersSec.options, durum.d)) durum.d = "";
  if (!sayfa.querySelector('[data-gun-sec="' + durum.gun + '"]')) durum.gun = "";

  var kodSayisi = {};
  satirlar.forEach(function (tr) { if (tr.dataset.girebilir === "1") kodSayisi[tr.dataset.kod] = (kodSayisi[tr.dataset.kod] || 0) + 1; });

  function kaydetSecim() {
    try { localStorage.setItem(ANAHTAR, JSON.stringify({ p: durum.p, d: durum.d, s: durum.s, g: durum.g, gun: durum.gun, benim: durum.benim })); } catch (e) { /* yok */ }
  }

  function uygula() {
    var q = kucuk(durum.q.trim()), n = 0, girilen = 0;
    cipler.forEach(function (c) { c.classList.toggle("secili", c.dataset.program === durum.p); });
    sayfa.querySelectorAll("[data-gun-sec]").forEach(function (c) { c.classList.toggle("secili", c.dataset.gunSec === durum.gun); });
    sayfa.querySelectorAll("[data-sinif-sec]").forEach(function (b) { b.classList.toggle("active", b.dataset.sinifSec === durum.s); });
    sayfa.querySelectorAll("[data-durum]").forEach(function (b) { b.classList.toggle("active", b.dataset.durum === durum.g); });
    dersSec.value = durum.d;
    if (benimKutu) benimKutu.checked = durum.benim;
    satirlar.forEach(function (tr) {
      var uy = (!durum.p || tr.dataset.program === durum.p) && (!durum.d || tr.dataset.dersBolum === durum.d) &&
               (!durum.s || tr.dataset.sinif === durum.s) && (!durum.g || tr.dataset.girildi === durum.g) &&
               (!durum.gun || tr.dataset.gun === durum.gun) && (!durum.benim || tr.dataset.girebilir === "1") &&
               (!q || kucuk(tr.dataset.ara + " " + tr.dataset.kisiler).indexOf(q) >= 0);
      tr.hidden = !uy;
      if (uy) { n++; if (tr.dataset.girildi === "1") girilen++; }
    });
    document.getElementById("etBos").hidden = n > 0;
    var parca = [];
    if (durum.gun) { var gc = sayfa.querySelector('[data-gun-sec="' + durum.gun + '"] .mz-pk-kod'); parca.push("Etüt <b>" + (gc ? gc.textContent : durum.gun) + "</b>"); }
    if (durum.p) parca.push("Program <b>" + durum.p + "</b>");
    if (durum.d) parca.push("Dersi veren <b>" + dersSec.options[dersSec.selectedIndex].text + "</b>");
    if (durum.s) parca.push("<b>" + durum.s + ". sınıf</b>");
    if (durum.g) parca.push(durum.g === "1" ? "yazılmış" : "yazılmamış");
    if (durum.benim) parca.push("girebileceklerim");
    if (q) parca.push("“" + durum.q.replace(/[<>&"]/g, "") + "”");
    document.getElementById("etSonuc").innerHTML = (parca.length ? parca.join(" · ") + " — " : "") + n + " satır, " + girilen +
      " yazılmış" + (parca.length ? ' · <a href="#" id="etTemizle">süzgeci temizle</a>' : "");
    var t = document.getElementById("etTemizle");
    if (t) t.addEventListener("click", function (e) {
      e.preventDefault(); durum = { p: "", d: "", s: "", g: "", gun: "", benim: false, q: "" }; ara.value = ""; kaydetSecim(); uygula();
    });
    document.getElementById("etExcel").href = sayfa.dataset.excel + (durum.p ? "?program=" + encodeURIComponent(durum.p) : "");
  }

  function ilerleme() {
    var say = {}, toplam = 0;
    satirlar.forEach(function (tr) { if (tr.dataset.girildi === "1") { say[tr.dataset.gun] = (say[tr.dataset.gun] || 0) + 1; toplam++; } });
    sayfa.querySelectorAll("[data-ilerleme]").forEach(function (el) {
      var g = say[el.dataset.ilerleme] || 0, t = +el.dataset.toplam;
      el.textContent = g + "/" + t;
      el.parentNode.querySelector(".mz-bar i").style.width = (t ? Math.round(100 * g / t) : 0) + "%";
      el.parentNode.classList.toggle("tamam", g === t);
    });
    document.getElementById("etToplam").textContent = toplam + "/" + satirlar.length;
  }

  // ---- satır durumu
  function secici(tr, alan) { return tr.querySelector('.et-secici[data-alan="' + alan + '"]'); }
  function yaz(tr, alan, kisi) {
    var s = secici(tr, alan), inp = s.querySelector(".et-kisi");
    inp.value = kisi ? kisi.ad : ""; inp.dataset.id = kisi ? kisi.id : ""; inp.dataset.onceki = inp.value;
    s.querySelector(".et-temizle").hidden = !kisi;
  }
  function goster(tr, s) {
    yaz(tr, 1, s.o1); yaz(tr, 2, s.o2);
    var ikinci = tr.querySelector(".et-ikinci");
    if (ikinci) {
      ikinci.disabled = !s.o1;
      if (s.o2) ikinci.checked = true;
      if (!s.o1) ikinci.checked = false;
      secici(tr, 2).hidden = !ikinci.checked;
    }
    tr.dataset.girildi = s.o1 ? "1" : "0";
    tr.dataset.kisiler = kucuk((s.o1 ? s.o1.ad : "") + " " + (s.o2 ? s.o2.ad : ""));
  }
  function kaydet(tr, hepsi) {
    var d = tr.querySelector(".mz-durum");
    var veri = { kod: tr.dataset.kod, bolum: tr.dataset.program, hepsi: !!hepsi,
                 ogretmen1: secici(tr, 1).querySelector(".et-kisi").dataset.id || null,
                 ogretmen2: tr.querySelector(".et-ikinci").checked ? (secici(tr, 2).querySelector(".et-kisi").dataset.id || null) : null };
    d.className = "mz-durum bekliyor"; d.innerHTML = '<i class="bi bi-arrow-repeat"></i>';
    fetch(sayfa.dataset.kaydet, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(veri), credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.hata || "Kaydedilemedi"); return j; }); })
      .then(function (j) {
        j.satirlar.forEach(function (s) {
          satirlar.forEach(function (x) {
            if (x.dataset.kod === tr.dataset.kod && x.dataset.program === s.bolum && x.dataset.girebilir === "1") {
              goster(x, s);
              var xd = x.querySelector(".mz-durum");
              xd.className = "mz-durum tamam"; xd.innerHTML = '<i class="bi bi-check-lg"></i>'; xd.title = "Kaydedildi";
            }
          });
        });
        ilerleme();
      })
      .catch(function (e) { d.className = "mz-durum hata"; d.innerHTML = '<i class="bi bi-exclamation-circle"></i>'; d.title = e.message; });
  }

  // ---- aranabilir seçici (tek ortak liste)
  var aktif = null, isik = -1, sonuc = [];
  function listeyiKapat() { liste.hidden = true; aktif = null; isik = -1; }
  function listeyiDoldur() {
    var q = kucuk(aktif.value.trim());
    sonuc = adaylar.filter(function (a) { return !q || kucuk(a.ad + " " + a.bolum).indexOf(q) >= 0; }).slice(0, 40);
    liste.innerHTML = "";
    if (!sonuc.length) { liste.innerHTML = '<li class="et-yok">Eşleşen öğretim elemanı yok</li>'; }
    sonuc.forEach(function (a, i) {
      var li = document.createElement("li");
      li.setAttribute("role", "option"); li.dataset.i = i;
      li.innerHTML = '<span></span><small></small>';
      li.firstChild.textContent = a.ad; li.lastChild.textContent = a.bolum;
      li.classList.toggle("isik", i === isik);
      liste.appendChild(li);
    });
    var k = aktif.getBoundingClientRect();
    liste.style.left = Math.max(8, Math.min(k.left, window.innerWidth - 340)) + "px";
    liste.style.top = (k.bottom + 2) + "px";
    liste.style.width = Math.max(k.width, 300) + "px";
    liste.hidden = false;
  }
  function sec(a) {
    var tr = aktif.closest("tr"), alan = aktif.closest(".et-secici").dataset.alan;
    yaz(tr, alan, a);
    if (alan === "1") tr.querySelector(".et-ikinci").disabled = false;
    listeyiKapat();
    kaydet(tr);
  }
  liste.addEventListener("mousedown", function (e) {
    var li = e.target.closest("li[data-i]");
    if (li && aktif) { e.preventDefault(); sec(sonuc[+li.dataset.i]); }
  });
  window.addEventListener("scroll", function () { if (aktif) listeyiDoldur(); }, true);

  satirlar.forEach(function (tr) {
    if (tr.dataset.girebilir !== "1") return;
    tr.querySelectorAll(".et-kisi").forEach(function (inp) {
      inp.dataset.onceki = inp.value;
      inp.addEventListener("focus", function () { aktif = inp; isik = -1; inp.select(); listeyiDoldur(); });
      inp.addEventListener("input", function () { aktif = inp; isik = 0; listeyiDoldur(); });
      inp.addEventListener("keydown", function (e) {
        if (liste.hidden) return;
        if (e.key === "ArrowDown") { e.preventDefault(); isik = Math.min(isik + 1, sonuc.length - 1); listeyiDoldur(); }
        else if (e.key === "ArrowUp") { e.preventDefault(); isik = Math.max(isik - 1, 0); listeyiDoldur(); }
        else if (e.key === "Enter") { e.preventDefault(); if (sonuc[isik]) sec(sonuc[isik]); }
        else if (e.key === "Escape") { inp.value = inp.dataset.onceki; listeyiKapat(); inp.blur(); }
      });
      inp.addEventListener("blur", function () {  // seçilmeden ayrılınca eski değer geri gelir
        setTimeout(function () { inp.value = inp.dataset.onceki; if (aktif === inp) listeyiKapat(); }, 150);
      });
    });
    tr.querySelectorAll(".et-temizle").forEach(function (b) {
      b.addEventListener("click", function () {
        var alan = b.closest(".et-secici").dataset.alan;
        yaz(tr, alan, null);
        if (alan === "2") { tr.querySelector(".et-ikinci").checked = false; secici(tr, 2).hidden = true; }
        kaydet(tr);
      });
    });
    var ikinci = tr.querySelector(".et-ikinci");
    ikinci.addEventListener("change", function () {
      secici(tr, 2).hidden = !ikinci.checked;
      if (ikinci.checked) secici(tr, 2).querySelector(".et-kisi").focus();
      else if (secici(tr, 2).querySelector(".et-kisi").dataset.id) { yaz(tr, 2, null); kaydet(tr); }
    });
    var hepsiBtn = tr.querySelector(".mz-hepsi");
    if (kodSayisi[tr.dataset.kod] > 1) hepsiBtn.hidden = false;
    hepsiBtn.addEventListener("click", function () { kaydet(tr, true); });
  });

  cipler.forEach(function (c) { c.addEventListener("click", function () { durum.p = durum.p === c.dataset.program ? "" : c.dataset.program; kaydetSecim(); uygula(); }); });
  sayfa.querySelectorAll("[data-gun-sec]").forEach(function (c) {
    c.addEventListener("click", function () { durum.gun = durum.gun === c.dataset.gunSec ? "" : c.dataset.gunSec; kaydetSecim(); uygula(); });
  });
  ["change", "input"].forEach(function (ol) { dersSec.addEventListener(ol, function () { if (durum.d !== dersSec.value) { durum.d = dersSec.value; kaydetSecim(); uygula(); } }); });
  sayfa.querySelectorAll("[data-sinif-sec]").forEach(function (b) { b.addEventListener("click", function () { durum.s = b.dataset.sinifSec; kaydetSecim(); uygula(); }); });
  sayfa.querySelectorAll("[data-durum]").forEach(function (b) { b.addEventListener("click", function () { durum.g = b.dataset.durum; kaydetSecim(); uygula(); }); });
  if (benimKutu) benimKutu.addEventListener("change", function () { durum.benim = benimKutu.checked; kaydetSecim(); uygula(); });
  ara.addEventListener("input", function () { durum.q = ara.value; uygula(); });
  window.addEventListener("pageshow", function () { uygula(); });
  ilerleme();
  uygula();
})();
