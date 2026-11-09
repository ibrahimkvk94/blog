/* Bildirimler: sağ üstte zil (okunmamış sayısı, liste, ayarlar), sağ altta 7 sn görünüp kaybolan pencereler.
   Sayfa her 30 sn'de bir /bildirim/durum/ sorar (sekme arka plandayken sormaz). Sayfa açılışında pencere çıkmaz; yalnız
   açıkken gelen yeni bildirimler çıkar. Birden çok sekme açıksa aynı bildirim yalnız bir kez pencere olur. */
(function () {
  var zil = document.getElementById("bildirimZili");
  if (!zil || !window.fetch) return;
  var rozet = zil.querySelector(".bildirim-rozet");
  var panel = document.getElementById("bildirimPaneli");
  var yigin = document.getElementById("bildirimYigini");
  var d = zil.dataset, son = parseInt(d.son, 10) || 0, zamanlayici = null;

  function csrf() {
    var e = document.querySelector("[name=csrfmiddlewaretoken]");
    if (e) return e.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }
  function gonder(url, veri) {
    var f = new FormData();
    Object.keys(veri || {}).forEach(function (k) { f.append(k, veri[k]); });
    return fetch(url, { method: "POST", body: f, credentials: "same-origin", headers: { "X-CSRFToken": csrf() } });
  }
  function kacis(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function sayac(n) {
    rozet.textContent = n > 99 ? "99+" : n;
    rozet.hidden = !n;
    zil.setAttribute("aria-label", n ? "Bildirimler, " + n + " okunmamış" : "Bildirimler");
  }
  function gosterilen() { try { return parseInt(localStorage.getItem("bildirim_gosterilen"), 10) || 0; } catch (e) { return 0; } }
  function isaretle(id) { try { if (id > gosterilen()) localStorage.setItem("bildirim_gosterilen", id); } catch (e) {} }
  function salla() { zil.classList.remove("salla"); void zil.offsetWidth; zil.classList.add("salla"); }

  function tost(b) {
    var el = document.createElement("div");
    el.className = "bildirim-tost";
    el.setAttribute("role", "status");
    el.innerHTML =
      '<span class="bildirim-ikon ' + kacis(b.renk) + '"><i class="bi bi-' + kacis(b.ikon) + '"></i></span>' +
      '<span class="bildirim-yazi"><a class="bildirim-baslik" href="' + kacis(b.url) + '">' + kacis(b.baslik) + "</a>" +
      (b.metin ? '<span class="bildirim-metin">' + kacis(b.metin) + "</span>" : "") +
      '<span class="bildirim-tost-alt"><a href="' + kacis(b.url) + '">Aç</a>' +
      '<button type="button" data-sessiz><i class="bi bi-bell-slash me-1"></i>Bu türü sessize al</button></span></span>' +
      '<button type="button" class="btn-close" aria-label="Kapat"></button><span class="bildirim-cubuk"></span>';
    function kapat() {
      el.classList.add("gidiyor");
      setTimeout(function () { el.remove(); }, 350);
    }
    el.querySelector(".btn-close").addEventListener("click", kapat);
    el.querySelector(".bildirim-cubuk").addEventListener("animationend", kapat);
    el.querySelector("[data-sessiz]").addEventListener("click", function (e) {
      var dugme = e.currentTarget;
      gonder(d.tercih, { tur: b.tur, mod: "sessiz" }).then(function (r) {
        if (r.ok) { dugme.outerHTML = "<span>Sessize alındı · ayarlardan değişir</span>"; }
      });
    });
    yigin.appendChild(el);
    while (yigin.children.length > 3) yigin.removeChild(yigin.firstChild);
  }

  function sor() {
    if (document.hidden) return;
    fetch(d.durum + "?son=" + son, { credentials: "same-origin" })
      .then(function (r) {
        var json = r.ok && (r.headers.get("content-type") || "").indexOf("json") >= 0;
        if (!json && zamanlayici) { clearInterval(zamanlayici); zamanlayici = null; } // oturum kapandı
        return json ? r.json() : null;
      })
      .then(function (v) {
        if (!v) return;
        sayac(v.okunmamis);
        var yeniVar = false;
        v.yeni.forEach(function (b) {
          if (b.id <= gosterilen()) return;
          isaretle(b.id);
          yeniVar = true;
          if (!b.sessiz) tost(b);
        });
        if (yeniVar) salla();
        son = Math.max(son, v.son || 0);
      })
      .catch(function () {});
  }
  isaretle(son);  // sayfa açılışında var olanlar pencere olmaz
  zamanlayici = setInterval(sor, 30000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden && zamanlayici) sor(); });

  // ---- zil paneli
  function yukle(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (r) { return r.ok ? r.text() : ""; })
      .then(function (h) { if (h) panel.innerHTML = h; });
  }
  zil.addEventListener("show.bs.dropdown", function () { yukle(d.liste); });
  panel.addEventListener("click", function (e) {
    var t = e.target.closest("[data-bildirim-tumu],[data-bildirim-ayarlar],[data-bildirim-geri],[data-bildirim-tercih]");
    if (!t) return;
    e.preventDefault();
    if (t.hasAttribute("data-bildirim-tumu")) {
      gonder(d.okundu).then(function (r) { return r.json(); }).then(function (v) { sayac(v.okunmamis); yukle(d.liste); });
    } else if (t.hasAttribute("data-bildirim-ayarlar")) {
      yukle(d.ayarlar);
    } else if (t.hasAttribute("data-bildirim-geri")) {
      yukle(d.liste);
    } else {
      gonder(d.tercih, { tur: t.dataset.bildirimTercih, mod: t.dataset.mod }).then(function (r) {
        if (!r.ok) return;
        t.parentNode.querySelectorAll("button").forEach(function (b) {
          b.classList.toggle("active", b === t);
          b.setAttribute("aria-pressed", b === t ? "true" : "false");
        });
      });
    }
  });
})();
