/* Anlık arama: yazdıkça süzülür, Enter gerekmez. Türkçe harf ve büyük-küçük harf duyarsız, sözcük sırası önemsiz.
   1) <input data-anlik-ara="#hedef" [data-anlik-oge="tbody tr"] [data-anlik-sayac="#sayi"]>
      Sayfadaki satırları süzer (satırın data-ara özelliği, yoksa metni). Satır data-anlik-haric ise dokunulmaz.
   2) <form data-canli="#bolge">
      Arama kutusuna yazdıkça / seçim değişince sayfayı arka planda yeniden ister, yalnız #bolge'yi değiştirir;
      adres çubuğu da güncellenir (yenileyince aynı sonuç). */
(function () {
  "use strict";
  const sade = (s) => (s || "").replace(/İ/g, "i").replace(/I/g, "ı").toLocaleLowerCase("tr")
    .replace(/ı/g, "i").replace(/ş/g, "s").replace(/ğ/g, "g").replace(/ü/g, "u").replace(/ö/g, "o").replace(/ç/g, "c")
    .normalize("NFD").replace(/[̀-ͯ]/g, "");
  window.kamyosisSade = sade;

  function anlik(kutu) {
    const hedef = document.querySelector(kutu.dataset.anlikAra);
    if (!hedef) return;
    const secici = kutu.dataset.anlikOge || "tbody tr";
    const sayac = kutu.dataset.anlikSayac ? document.querySelector(kutu.dataset.anlikSayac) : null;
    function suz() {
      const aranan = sade(kutu.value).split(/\s+/).filter(Boolean);
      let n = 0;
      hedef.querySelectorAll(secici).forEach((o) => {
        if (o.hasAttribute("data-anlik-haric")) return;
        const metin = sade(o.dataset.ara || o.textContent);
        const uyar = aranan.every((s) => metin.includes(s));
        o.hidden = !uyar;
        if (uyar) n++;
      });
      if (sayac) sayac.textContent = n;
    }
    kutu.addEventListener("input", suz);
    kutu.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
    if (kutu.value) suz();
  }

  function canli(form) {
    const bolgeSecici = form.dataset.canli;
    let zaman = null, istek = null;
    function getir() {
      const bolge = document.querySelector(bolgeSecici);
      if (!bolge) return;
      const params = new URLSearchParams(new FormData(form));
      for (const [k, v] of [...params.entries()]) if (v === "") params.delete(k);
      params.delete("sayfa");
      const url = (form.getAttribute("action") || location.pathname) + (params.toString() ? "?" + params : "");
      if (istek) istek.abort();
      istek = new AbortController();
      bolge.classList.add("canli-yukleniyor");
      fetch(url, { signal: istek.signal, credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
        .then((r) => r.text())
        .then((html) => {
          const yeni = new DOMParser().parseFromString(html, "text/html").querySelector(bolgeSecici);
          if (yeni) bolge.innerHTML = yeni.innerHTML;
          history.replaceState(history.state, "", url);
          bolge.classList.remove("canli-yukleniyor");
          document.dispatchEvent(new CustomEvent("kamyosis:canli", { detail: bolge }));
        })
        .catch(() => bolge.classList.remove("canli-yukleniyor"));
    }
    form.querySelectorAll('input[type="search"], input[name="q"]').forEach((i) => {
      i.addEventListener("input", () => { clearTimeout(zaman); zaman = setTimeout(getir, 200); });
    });
    form.querySelectorAll("select").forEach((s) => s.addEventListener("change", () => { clearTimeout(zaman); getir(); }));
    form.addEventListener("submit", (e) => { e.preventDefault(); clearTimeout(zaman); getir(); });
  }

  document.querySelectorAll("[data-anlik-ara]").forEach(anlik);
  document.querySelectorAll("form[data-canli]").forEach(canli);
})();
