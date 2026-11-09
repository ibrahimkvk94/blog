/* Mazeret toplu tablosu (templates/mazeret/tablo.html): satır = personel, sütun = gün × oturum.
   Hücreye tıklama seçili işareti koyar / kaldırır; basılı tutup sürüklemek aynı işlemi geçtiği hücrelere uygular.
   Gün, oturum ya da kişi başlığı bütün sütunu / satırı işaretler (hepsi zaten o işaretteyse kaldırır).
   Personel yoklamasında izinli olunan oturumlar açılışta ✗ olarak gelir (kaydedilince bildirime yazılır). */
(function () {
  "use strict";
  const form = document.getElementById("mzTabloForm");
  if (!form) return;
  const veri = JSON.parse(document.getElementById("mzVeriJson").textContent || "{}");
  const izin = JSON.parse(document.getElementById("mzIzinJson").textContent || "{}");
  const girdi = document.getElementById("mzVeriler");
  const degisiklik = document.getElementById("mzDegisiklik");
  const hucreler = Array.from(form.querySelectorAll(".mz-hucre"));
  const duzenle = !!form.querySelector(".mz-duzenle");
  const ISARET = { no: "✗", maybe: "?" };
  const ilk = JSON.stringify(veri);
  let kirli = false;

  const durum = (h) => (veri[h.dataset.p] || {})[h.dataset.k] || "";
  function yaz(h, d) {
    const s = veri[h.dataset.p] || (veri[h.dataset.p] = {});
    if (d) s[h.dataset.k] = d; else delete s[h.dataset.k];
  }
  function ciz(h) {
    const d = durum(h), iz = (izin[h.dataset.p] || {})[h.dataset.k];
    h.textContent = ISARET[d] || "";
    h.className = "mz-hucre" + (d ? " mz-" + d : "") + (iz ? " mz-izin" : "");
    h.title = iz ? iz + " (personel yoklaması)" : "";
    h.setAttribute("aria-pressed", d ? "true" : "false");
  }
  function guncelle() {
    kirli = JSON.stringify(veri) !== ilk || kirli;
    if (degisiklik) degisiklik.hidden = !kirli;
  }
  window.mzKirli = () => kirli;

  // izinli oturumlar: boşsa ✗
  if (duzenle) {
    let n = 0;
    const kisiler = new Set();
    hucreler.forEach((h) => {
      const iz = (izin[h.dataset.p] || {})[h.dataset.k];
      if (iz && durum(h) !== "no") { yaz(h, "no"); n++; kisiler.add(h.dataset.p); }
    });
    const not = document.getElementById("mzIzinNotu");
    if (n && not) {
      not.hidden = false;
      not.querySelector("span").textContent = `${kisiler.size} kişinin personel yoklamasındaki izin / rapor / görev kaydı nedeniyle ${n} oturuma ✗ kondu. Kaydedince bildirime yazılır.`;
      kirli = true;
    }
  }
  hucreler.forEach(ciz);
  guncelle();
  if (!duzenle) return;

  const firca = () => (form.querySelector('input[name="firca"]:checked') || {}).value || "";
  function topluUygula(liste) {
    const f = firca();
    const hepsiAyni = liste.every((h) => durum(h) === f);
    liste.forEach((h) => { yaz(h, hepsiAyni ? "" : f); ciz(h); });
    guncelle();
  }

  // tıklama ve sürükleme
  let boya = null; // sürüklerken konacak değer
  form.addEventListener("pointerdown", (e) => {
    const h = e.target.closest(".mz-hucre");
    if (!h || e.button !== 0) return;
    e.preventDefault();
    const f = firca();
    boya = durum(h) === f ? "" : f;
    yaz(h, boya); ciz(h); guncelle();
  });
  form.addEventListener("pointerover", (e) => {
    if (boya === null || !(e.buttons & 1)) return;
    const h = e.target.closest(".mz-hucre");
    if (h && durum(h) !== boya) { yaz(h, boya); ciz(h); guncelle(); }
  });
  addEventListener("pointerup", () => { boya = null; });
  // klavye: Enter / boşluk hücreyi değiştirir
  form.addEventListener("keydown", (e) => {
    const h = e.target.closest(".mz-hucre");
    if (h && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); topluUygula([h]); }
  });
  form.querySelectorAll(".mz-baslik").forEach((b) => b.addEventListener("click", () => {
    let liste;
    if (b.dataset.satir) liste = hucreler.filter((h) => h.dataset.p === b.dataset.satir);
    else if (b.dataset.sira !== undefined) liste = hucreler.filter((h) => h.dataset.gun === b.dataset.gun && h.dataset.sira === b.dataset.sira);
    else liste = hucreler.filter((h) => h.dataset.gun === b.dataset.gun);
    topluUygula(liste);
  }));

  form.addEventListener("submit", () => {
    girdi.value = JSON.stringify(veri);
    kirli = false;
  });
  addEventListener("beforeunload", (e) => { if (kirli) { e.preventDefault(); e.returnValue = ""; } });
})();
