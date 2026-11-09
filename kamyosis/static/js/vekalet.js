/* Vekâlet formu (templates/vekalet/islemler.html):
   - Vekâlet veren seçilince görev kutusu boşsa (ya da önceki öneriyse) bölüm başkanlığı / görev unvanı yazılır.
   - Verenin personel yoklamasındaki yaklaşan izin / rapor / görev kayıtları düğme olarak çıkar; tıklayınca
     başlangıç, bitiş ve neden doldurulur. */
(function () {
  "use strict";
  const form = document.getElementById("vkForm");
  if (!form) return;
  const oku = (id) => { try { return JSON.parse(document.getElementById(id).textContent || "{}"); } catch (e) { return {}; } };
  const gorevler = oku("vkGorevJson"), izinler = oku("vkIzinJson");
  const veren = form.querySelector('[name="veren"]'), gorev = form.querySelector('[name="gorev"]');
  const bas = form.querySelector('[name="baslangic"]'), bit = form.querySelector('[name="bitis"]');
  const neden = form.querySelector('[name="neden"]');
  const kutu = document.getElementById("vkIzinler");
  let oneri = gorev.value && gorevler[veren.value] === gorev.value ? gorev.value : "";

  function nedenYaz(deger) {
    if (neden.tomselect) neden.tomselect.setValue(deger, true); else neden.value = deger;
  }

  function guncelle(ilk) {
    const g = gorevler[veren.value] || "";
    if (!ilk && (!gorev.value || gorev.value === oneri)) { gorev.value = g; oneri = g; }
    kutu.querySelectorAll("button").forEach((b) => b.remove());
    const liste = izinler[veren.value] || [];
    kutu.hidden = !liste.length;
    liste.forEach((k) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "vk-izin-cip";
      b.textContent = `${k.ad} · ${k.metin}`;
      b.title = "Başlangıç, bitiş ve nedeni bu kayda göre doldur";
      b.addEventListener("click", () => { bas.value = k.bas; bit.value = k.bit; nedenYaz(k.neden); });
      kutu.appendChild(b);
    });
  }
  veren.addEventListener("change", () => guncelle(false));
  guncelle(true);
  // bitiş başlangıçtan önce olamaz
  bas.addEventListener("change", () => { bit.min = bas.value; if (bit.value && bit.value < bas.value) bit.value = bas.value; });
  if (bas.value) bit.min = bas.value;
})();
