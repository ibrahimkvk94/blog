/* Veri listelerinde ortak sıralama: tablo, düzenleme ekranındaki kayıt listesi ve dersler sayfası.
 *
 * Sıralanacak öğeler data-s-<anahtar> öznitelikleri taşır (sunucu yazar); <select data-sort> değeri "anahtar"
 * (artan) ya da "-anahtar" (azalan), boş = varsayılan sıra. Seçim tarayıcıda data-sort-store adıyla saklanır;
 * aynı adı kullanan ekranlar (ör. öğretmen tablosu ve öğretmen düzenleme listesi) aynı sırayı paylaşır.
 * Boş değerler yöne bakılmaksızın sona gider; eşitlikte varsayılan sıra (data-s-i) korunur.
 */
(function () {
  "use strict";
  const collator = new Intl.Collator("tr", { numeric: true, sensitivity: "base" });
  const isNumber = (v) => v !== "" && !isNaN(Number(v));

  function compare(a, b) {
    if (isNumber(a) && isNumber(b)) return Number(a) - Number(b);
    return collator.compare(a, b);
  }

  function order(items, value) {
    const desc = value.startsWith("-");
    const key = desc ? value.slice(1) : value;
    const index = (el) => Number(el.getAttribute("data-s-i") || 0);
    return items.slice().sort((x, y) => {
      if (!key) return index(x) - index(y);
      const a = x.getAttribute("data-s-" + key) || "", b = y.getAttribute("data-s-" + key) || "";
      if (a === "" || b === "") return a === b ? index(x) - index(y) : (a === "" ? 1 : -1);
      return (desc ? -compare(a, b) : compare(a, b)) || index(x) - index(y);
    });
  }

  function store(name, value) {
    try {
      if (value === undefined) return localStorage.getItem(name);
      localStorage.setItem(name, value);
    } catch (e) { /* özel pencere: yalnızca bu sayfada geçerli */ }
    return null;
  }

  /* select: <select data-sort>; container: öğelerin ebeveyni; items(): sıralanacak öğeler;
     after(sıralı öğeler): sıralamadan sonra (ör. önceki/sonraki bağlantıları). */
  function bind(select, container, items, after) {
    const name = select.dataset.sortStore;
    const saved = name ? store(name) : null;
    if (saved !== null && [...select.options].some((o) => o.value === saved)) select.value = saved;
    const apply = () => {
      const sorted = order(items(), select.value);
      const tail = [...container.children].filter((el) => !sorted.includes(el));  // ör. "kayıt yok" satırı
      sorted.concat(tail).forEach((el) => container.appendChild(el));
      if (after) after(sorted);
    };
    select.addEventListener("change", () => { if (name) store(name, select.value); apply(); });
    apply();
    return apply;
  }

  window.DataSort = { order, bind };

  // Bildirimsel kullanım: <select data-sort data-sort-target="seçici"> ve hedefin içindeki [data-s-i] öğeleri.
  document.querySelectorAll("select[data-sort][data-sort-target]").forEach((select) => {
    const container = document.querySelector(select.dataset.sortTarget);
    if (container) bind(select, container, () => [...container.querySelectorAll(":scope > [data-s-i]")]);
  });
})();
