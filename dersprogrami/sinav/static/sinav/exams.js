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

  // ---- KAMYOSİS: bölüm süzgeci: <select data-ex-group="#hedef"> → hedefin data-group'u eşleşen satırları kalır ----
  $$("[data-ex-group]").forEach((select) => {
    const target = document.querySelector(select.dataset.exGroup);
    if (!target) return;
    const apply = () => {
      $$("[data-group]", target).forEach((row) => {
        row.classList.toggle("ex-group-hidden", Boolean(select.value) && row.dataset.group !== select.value);
      });
    };
    select.addEventListener("change", apply);
    apply();
  });

  // ---- KAMYOSİS: sıralama: table.ex-sortable th[data-sort] tıklanınca (tekrar tıklama ters çevirir) ----------
  //      hücrenin data-value'su varsa o, yoksa metni; ikisi de sayıysa sayı olarak karşılaştırılır
  $$("table.ex-sortable").forEach((table) => {
    const body = table.tBodies[0];
    $$("th[data-sort]", table).forEach((th) => {
      th.style.cursor = "pointer";
      th.title = th.title || "Sıralamak için tıklayın";
      th.addEventListener("click", () => {
        const col = Array.from(th.parentNode.children).indexOf(th);
        const asc = th.dataset.dir !== "asc";
        $$("th[data-sort]", table).forEach((h) => { delete h.dataset.dir; h.classList.remove("ex-sort-asc", "ex-sort-desc"); });
        th.dataset.dir = asc ? "asc" : "desc";
        th.classList.add(asc ? "ex-sort-asc" : "ex-sort-desc");
        const key = (row) => {
          const cell = row.children[col];
          return cell ? (cell.dataset.value !== undefined ? cell.dataset.value : cell.textContent.trim()) : "";
        };
        const rows = Array.from(body.rows);
        rows.sort((a, b) => {
          const x = key(a), y = key(b), nx = parseFloat(x), ny = parseFloat(y);
          const r = !isNaN(nx) && !isNaN(ny) ? nx - ny : x.localeCompare(y, "tr");
          return asc ? r : -r;
        });
        rows.forEach((r) => body.appendChild(r));
      });
    });
  });

  // ---- KAMYOSİS: muaf işaretlenince satırdaki rol kutuları boşalır; rol seçilince muaflık kalkar -------------
  $$("[data-ex-row-exempt]").forEach((box) => {
    const row = box.closest("tr");
    const roles = $$("[data-ex-role]", row);
    box.addEventListener("change", () => {
      if (box.checked) roles.forEach((r) => { r.checked = false; });
      else if (!roles.some((r) => r.checked)) roles.forEach((r) => { r.checked = r.dataset.exRole !== "A"; });
    });
    roles.forEach((r) => r.addEventListener("change", () => { if (r.checked) box.checked = false; }));
  });

  // ---- açılır menü (details.dropdown): dışarı tıklanınca kapanır --------------------------------
  document.addEventListener("click", (e) => {
    $$("details.dropdown[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  });
})();
