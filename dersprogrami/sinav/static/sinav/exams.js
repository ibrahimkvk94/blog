/* Sınav programı sayfaları: arama süzgeci (Türkçe harf duyarsız), tümünü seç, açılır menü. */
(function () {
  "use strict";
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const fold = (s) => String(s || "").toLocaleLowerCase("tr").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ı/g, "i");

  // ---- arama: data-ex-filter="#hedef" → hedefin data-search taşıyan çocukları süzülür ----------
  $$("[data-ex-filter]").forEach((input) => {
    const target = document.querySelector(input.dataset.exFilter);
    if (!target) return;
    const apply = () => {
      const words = fold(input.value).split(/\s+/).filter(Boolean);
      $$("[data-search]", target).forEach((row) => {
        const text = row.dataset.search;
        row.hidden = words.length > 0 && !words.every((w) => text.includes(w));
      });
    };
    input.addEventListener("input", apply);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
    if (input.value) apply();
  });

  // ---- tümünü seç (yalnızca görünen satırlar) --------------------------------------------------
  $$("[data-ex-all]").forEach((box) => {
    const table = box.closest("table");
    box.addEventListener("change", () => {
      $$("tbody tr", table).forEach((tr) => {
        const cb = tr.querySelector("input[name=sel]");
        if (cb && !tr.hidden) cb.checked = box.checked;
      });
    });
  });

  // ---- açılır menü (details.dropdown): dışarı tıklanınca kapanır --------------------------------
  document.addEventListener("click", (e) => {
    $$("details.dropdown[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  });
})();
