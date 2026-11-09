/* Sol menüde arama: yazdıkça menüdeki sayfalar süzülür (Türkçe harf ve büyük-küçük harf duyarsız, sözcük sırası
   önemsiz). Bir dalın adı eşleşirse altındaki bütün sayfalar görünür; eşleşen sayfanın kapalı dalları açılır.
   Enter ilk (ya da oklarla seçilen) sonuca gider, Esc temizler. Klavyede "/" ya da Ctrl+K kutuya götürür. */
(function () {
  "use strict";
  var kutu = document.getElementById("menuAra");
  var menu = document.querySelector(".kenar-menu");
  var kenar = document.getElementById("kenarCubugu");
  if (!kutu || !menu || !kenar) return;
  var yok = document.getElementById("menuAraYok");
  var sade = window.kamyosisSade || function (s) {
    return (s || "").replace(/İ/g, "i").replace(/I/g, "ı").toLocaleLowerCase("tr").replace(/ı/g, "i")
      .replace(/ş/g, "s").replace(/ğ/g, "g").replace(/ü/g, "u").replace(/ö/g, "o").replace(/ç/g, "c");
  };
  var secili = -1, sonuclar = [];

  function ad(li) {
    var a = li.querySelector(":scope > a");
    return a ? sade(a.textContent) : "";
  }

  // li ve altları: görünürse true döner; eşleşen yaprak bağlantıları sonuclar'a eklenir
  function suz(li, sozler, ustEslesti) {
    var alt = li.querySelector(":scope > ul");
    var metin = ad(li);
    var eslesti = ustEslesti || sozler.every(function (s) { return metin.indexOf(s) >= 0; });
    var gorunur = eslesti;
    if (alt) {
      var cocukGorunur = false;
      alt.querySelectorAll(":scope > li").forEach(function (c) { if (suz(c, sozler, eslesti)) cocukGorunur = true; });
      gorunur = eslesti || cocukGorunur;
      alt.classList.toggle("ara-acik", gorunur);
    } else if (eslesti) {
      var a = li.querySelector(":scope > a");
      if (a) sonuclar.push(a);
    }
    li.classList.toggle("ara-gizli", !gorunur);
    return gorunur;
  }

  function isaretle(i) {
    sonuclar.forEach(function (a, j) { a.classList.toggle("ara-secili", j === i); });
    secili = i;
    if (sonuclar[i]) sonuclar[i].scrollIntoView({ block: "nearest" });
  }

  function uygula() {
    var sozler = sade(kutu.value).split(/\s+/).filter(Boolean);
    sonuclar = [];
    menu.classList.toggle("aramada", sozler.length > 0);
    menu.querySelectorAll(".ara-secili").forEach(function (a) { a.classList.remove("ara-secili"); });
    if (!sozler.length) {
      menu.querySelectorAll(".ara-gizli").forEach(function (e) { e.classList.remove("ara-gizli"); });
      menu.querySelectorAll(".ara-acik").forEach(function (e) { e.classList.remove("ara-acik"); });
      if (yok) yok.hidden = true;
      secili = -1;
      return;
    }
    menu.querySelectorAll(":scope > ul").forEach(function (ul) {
      var var_ = false;
      ul.querySelectorAll(":scope > li").forEach(function (li) { if (suz(li, sozler, false)) var_ = true; });
      ul.classList.toggle("ara-gizli", !var_);
      var b = ul.previousElementSibling;
      if (b && b.classList.contains("menu-baslik")) b.classList.toggle("ara-gizli", !var_);
    });
    if (yok) yok.hidden = sonuclar.length > 0;
    isaretle(sonuclar.length ? 0 : -1);
  }

  kutu.addEventListener("input", uygula);
  kutu.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!sonuclar.length) return;
      e.preventDefault();
      var n = sonuclar.length;
      isaretle(((secili < 0 ? -1 : secili) + (e.key === "ArrowDown" ? 1 : -1) + n) % n);
    } else if (e.key === "Enter") {
      var a = sonuclar[secili] || sonuclar[0];
      if (a) { e.preventDefault(); a.click(); }
    } else if (e.key === "Escape") {
      if (kutu.value) { e.preventDefault(); kutu.value = ""; uygula(); } else { kutu.blur(); }
    }
  });

  // "/" ya da Ctrl+K: menü aramasına git (yazı alanındayken değil)
  document.addEventListener("keydown", function (e) {
    var yer = e.target, yaziAlani = yer && (yer.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(yer.tagName));
    var kisayol = (e.key === "/" && !yaziAlani && !e.ctrlKey && !e.metaKey && !e.altKey) ||
      ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K"));
    if (!kisayol) return;
    e.preventDefault();
    if (window.matchMedia && matchMedia("(max-width: 991.98px)").matches && window.bootstrap) {
      bootstrap.Offcanvas.getOrCreateInstance(kenar).show();
      setTimeout(function () { kutu.focus(); kutu.select(); }, 250);
      return;
    }
    if (document.documentElement.classList.contains("kenar-dar")) kenar.classList.add("gezinti");
    kutu.focus();
    kutu.select();
  });

  // daraltılmış menüde yalnız büyüteç görünür: basınca menü açılır, kutuya geçilir
  kutu.parentElement.addEventListener("click", function () {
    if (document.documentElement.classList.contains("kenar-dar") && !kenar.classList.contains("gezinti")) {
      kenar.classList.add("gezinti");
      kutu.focus();
    }
  });

  // aramadan bir sayfaya gidilince kutu bir sonraki sayfada boş başlar (tarayıcı geri gelirse de)
  addEventListener("pageshow", function () { if (kutu.value) { kutu.value = ""; uygula(); } });
})();
