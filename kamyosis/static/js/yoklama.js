/* Personel yoklaması: kayıt formu (gün / saatlik), hızlı ekleme penceresi, listede arama. */
(function () {
  "use strict";
  const gunFarki = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000);

  const sadeMetin = (s) => (s || "").replace(/İ/g, "i").replace(/I/g, "ı").toLocaleLowerCase("tr").replace(/ı/g, "i")
    .replace(/ş/g, "s").replace(/ğ/g, "g").replace(/ü/g, "u").replace(/ö/g, "o").replace(/ç/g, "c");
  const YARIM = { oo: ["08:00", "12:30", "Öğleden önce"], os: ["13:30", "17:00", "Öğleden sonra"] };
  const kacis = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function formuHazirla(kap) {
    const bicimler = kap.querySelectorAll("[data-bicim]");
    const bas = kap.querySelector("[data-bas-tarih]");
    const bit = kap.querySelector("[data-bit-tarih]");
    const bs = kap.querySelector('[name="bas_saat"]');
    const bt = kap.querySelector('[name="bit_saat"]');
    const sure = kap.querySelector("[data-sure]");
    const hakSonuc = kap.querySelector("[data-hak-sonuc]");
    const turSec = kap.querySelector("[data-tur-sec]");
    const hazir = kap.querySelector("[data-hazir-saatler]");
    const tarihEtiketi = kap.querySelector("[data-tarih-etiketi]");
    const hakVeri = kap.dataset.hak ? JSON.parse((document.getElementById(kap.dataset.hak) || {}).textContent || "{}") : null;
    const secili = () => (Array.from(bicimler).find((r) => r.checked) || {}).value || "tam";
    const seciliTur = () => turSec ? turSec.value : (kap.querySelector('[name="tur"]:checked') || {}).value;
    const secenek = (v) => turSec ? turSec.querySelector('option[value="' + v + '"]') : null;
    const bicimSec = (deger) => { const r = Array.from(bicimler).find((x) => x.value === deger); if (r) r.checked = true; };

    // aranabilir açılır liste: grup başlıkları, renkli nokta ve kısaltma
    if (turSec && window.TomSelect && !turSec.tomselect) {
      const renk = (v) => { const o = secenek(v); return o ? o.dataset.renk : "#64748b"; };
      const kisa = (v) => { const o = secenek(v); return o ? o.dataset.kisa : ""; };
      new TomSelect(turSec, {
        create: false, maxOptions: null, dropdownParent: "body", lockOptgroupOrder: true,
        searchField: [], sortField: [{ field: "$order" }],
        score: (arama) => {
          const a = sadeMetin(arama).split(/\s+/).filter(Boolean);
          return (it) => (a.every((p) => sadeMetin(it.text).includes(p)) ? 1 : 0);
        },
        render: {
          option: (d) => '<div class="yk-tur-secenek"><span class="yk-nokta" style="--renk:' + renk(d.value) + '"></span>' +
            kacis(d.text) + "<small>" + kacis(kisa(d.value)) + "</small></div>",
          item: (d) => '<div class="yk-tur-secenek"><span class="yk-nokta" style="--renk:' + renk(d.value) + '"></span>' +
            kacis(d.text) + "</div>",
          no_results: () => '<div class="no-results px-2 py-1 text-secondary">Eşleşen tür yok</div>',
        },
        onDropdownOpen: function () { this.setTextboxValue(""); this.refreshOptions(false); },
      });
    }
    function turDegisti() {
      const o = secenek(seciliTur());
      const yarim = !!(o && o.dataset.yarim);
      kap.querySelectorAll("[data-yarim-secenek]").forEach((el) => { el.hidden = !yarim; });
      if (!yarim && YARIM[secili()]) bicimSec("tam");
      const saatler = o && o.dataset.saatler ? o.dataset.saatler.split(",") : [];
      if (hazir) {
        hazir.hidden = !saatler.length;
        hazir.innerHTML = saatler.length ? '<span class="small text-secondary me-1">Hazır saatler:</span>' + saatler.map((s) =>
          '<button type="button" class="yk-hazir-saat" data-aralik="' + s + '">' + s.replace("-", "–") + "</button>").join("") : "";
      }
      kap.querySelectorAll("[data-tur-hizli]").forEach((b) => b.classList.toggle("secili", b.dataset.turHizli === seciliTur()));
    }
    // seçilen türün yıllık hakkı: bu kayıttan sonra kalan (yıl yıl; takvim günü)
    function hakMetni(basT, bitT) {
      const h = hakVeri && hakVeri[seciliTur()];
      if (!h) return "";
      const parcalar = [];
      for (let yil = Number(basT.slice(0, 4)); yil <= Number(bitT.slice(0, 4)); yil++) {
        const a = basT > `${yil}-01-01` ? basT : `${yil}-01-01`, b = bitT < `${yil}-12-31` ? bitT : `${yil}-12-31`;
        const n = gunFarki(a, b) + 1;
        if (n <= 0) continue;
        const kullanilan = (h.kullanilan || {})[String(yil)];
        if (kullanilan === undefined) continue;
        const kalan = h.hak - kullanilan - n;
        parcalar.push({ yil, metin: kalan >= 0 ? `${yil}: kalan ${h.hak - kullanilan} → ${kalan} gün` : `${yil}: hak aşımı ${-kalan} gün (kalan ${h.hak - kullanilan})`, asim: kalan < 0 });
      }
      if (!parcalar.length) return "";
      hakSonuc.classList.toggle("text-danger", parcalar.some((p) => p.asim));
      hakSonuc.classList.toggle("fw-semibold", parcalar.some((p) => p.asim));
      return `· ${h.ad} ${parcalar.map((p) => p.metin).join(", ")}`;
    }
    const saatFarki = (a, b) => { const [h1, m1] = a.split(":").map(Number), [h2, m2] = b.split(":").map(Number); return (h2 * 60 + m2) - (h1 * 60 + m1); };
    const sureMetni = (dk) => `${Math.floor(dk / 60)} saat${dk % 60 ? " " + (dk % 60) + " dk" : ""}`;
    function guncelle() {
      const b = secili();
      kap.querySelectorAll("[data-sadece]").forEach((el) => { el.hidden = el.dataset.sadece !== b; });
      if (tarihEtiketi) tarihEtiketi.textContent = b === "tam" ? "Başlangıç tarihi" : "Tarih";
      if (bit) bit.required = b === "tam";
      if (bit && bas && bas.value && (!bit.value || bit.value < bas.value)) bit.value = bas.value;
      if (b !== "saat") kap.querySelectorAll("[data-aralik].secili").forEach((x) => x.classList.remove("secili"));
      if (!sure) return;
      if (hakSonuc) { hakSonuc.textContent = ""; hakSonuc.classList.remove("text-danger", "fw-semibold"); }
      if (b === "tam" && bas.value && bit.value) {
        const n = gunFarki(bas.value, bit.value) + 1;
        sure.textContent = n > 0 ? `${n} gün` : "Bitiş başlangıçtan önce olamaz.";
        if (n > 0 && hakSonuc) hakSonuc.textContent = hakMetni(bas.value, bit.value);
      } else if (YARIM[b]) {
        const [a, c, ad] = YARIM[b];
        sure.textContent = `${ad}: ${a}–${c} (${sureMetni(saatFarki(a, c))})`;
      } else if (b === "saat" && bs.value && bt.value) {
        const dk = saatFarki(bs.value, bt.value);
        sure.textContent = dk > 0 ? sureMetni(dk) : "Bitiş saati başlangıçtan sonra olmalı.";
      } else sure.textContent = "";
    }
    bicimler.forEach((r) => r.addEventListener("change", guncelle));
    if (turSec) turSec.addEventListener("change", () => { turDegisti(); guncelle(); });
    kap.querySelectorAll('[name="tur"][type="radio"]').forEach((r) => r.addEventListener("change", guncelle));
    kap.addEventListener("click", (e) => {
      const h = e.target.closest("[data-tur-hizli]");
      if (h && turSec) {
        if (turSec.tomselect) turSec.tomselect.setValue(h.dataset.turHizli);
        else { turSec.value = h.dataset.turHizli; turSec.dispatchEvent(new Event("change")); }
        return;
      }
      const s = e.target.closest("[data-aralik]");
      if (s) {
        const [a, c] = s.dataset.aralik.split("-");
        bicimSec("saat");
        bs.value = a;
        bt.value = c;
        guncelle();
        s.classList.add("secili");
      }
    });
    [bas, bit, bs, bt].forEach((el) => el && el.addEventListener("input", guncelle));
    turDegisti();
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
    kutu.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
    kutu.addEventListener("input", () => {
      const k = sade(kutu.value).split(/\s+/).filter(Boolean);
      hedef.querySelectorAll("[data-ara]").forEach((s) => {
        const m = sade(s.dataset.ara);
        s.hidden = k.length > 0 && !k.every((w) => m.includes(w));
      });
    });
  });
})();
