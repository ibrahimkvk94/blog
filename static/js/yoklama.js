/* Personel yoklaması: kayıt formu (gün / saatlik), hızlı ekleme penceresi, listede arama. */
(function () {
  "use strict";
  const gunFarki = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000);

  function formuHazirla(kap) {
    const bicimler = kap.querySelectorAll("[data-bicim]");
    const bas = kap.querySelector("[data-bas-tarih]");
    const bit = kap.querySelector("[data-bit-tarih]");
    const bs = kap.querySelector('[name="bas_saat"]');
    const bt = kap.querySelector('[name="bit_saat"]');
    const sure = kap.querySelector("[data-sure]");
    const secili = () => (Array.from(bicimler).find((r) => r.checked) || {}).value || "tam";
    function guncelle() {
      const b = secili();
      kap.querySelectorAll("[data-sadece]").forEach((el) => { el.hidden = el.dataset.sadece !== b; });
      if (bit) bit.required = b === "tam";
      if (bit && bas && bas.value && (!bit.value || bit.value < bas.value)) bit.value = bas.value;
      if (!sure) return;
      if (b === "tam" && bas.value && bit.value) {
        const n = gunFarki(bas.value, bit.value) + 1;
        sure.textContent = n > 0 ? `${n} gün` : "Bitiş başlangıçtan önce olamaz.";
      } else if (b === "saat" && bs.value && bt.value) {
        const [h1, m1] = bs.value.split(":").map(Number), [h2, m2] = bt.value.split(":").map(Number);
        const dk = (h2 * 60 + m2) - (h1 * 60 + m1);
        sure.textContent = dk > 0 ? `${Math.floor(dk / 60)} saat${dk % 60 ? " " + (dk % 60) + " dk" : ""}` : "Bitiş saati başlangıçtan sonra olmalı.";
      } else sure.textContent = "";
    }
    bicimler.forEach((r) => r.addEventListener("change", guncelle));
    [bas, bit, bs, bt].forEach((el) => el && el.addEventListener("input", guncelle));
    guncelle();
  }
  document.querySelectorAll("[data-yk-form]").forEach(formuHazirla);

  // hızlı ekleme: listede "+ Kayıt" düğmesi pencereyi o kişi için açar
  const pencere = document.getElementById("ykEkle");
  if (pencere) {
    pencere.addEventListener("show.bs.modal", (e) => {
      const d = e.relatedTarget;
      if (!d) return;
      pencere.querySelector("form").action = d.dataset.url;
      pencere.querySelector("[data-kisi-ad]").textContent = d.dataset.ad;
      pencere.querySelector("[data-kisi-kunye]").textContent = d.dataset.kunye || "";
    });
  }

  // listede arama (Türkçe harf duyarsız)
  const sade = (s) => (s || "").replace(/İ/g, "i").replace(/I/g, "ı").toLocaleLowerCase("tr")
    .normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ı/g, "i");
  document.querySelectorAll("[data-yk-ara]").forEach((kutu) => {
    const hedef = document.querySelector(kutu.dataset.ykAra);
    if (!hedef) return;
    kutu.addEventListener("input", () => {
      const k = sade(kutu.value).split(/\s+/).filter(Boolean);
      hedef.querySelectorAll("[data-ara]").forEach((s) => {
        const m = sade(s.dataset.ara);
        s.hidden = k.length > 0 && !k.every((w) => m.includes(w));
      });
    });
  });
})();
