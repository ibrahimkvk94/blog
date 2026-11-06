/* Genel bakıştaki Sürümler tablosu: sağ tık (telefonda uzun basma) ya da satırdaki ⋯ düğmesi menüyü açar.
 *
 * Menü: aç, yayından kaldır (yayındaki satırda), sil, seçerek sil (onay kutuları ve seçim çubuğu), tüm sürümleri sil. Silme ortak pencereden
 * okul düzeyindeki timetables_delete işlemine gider (ids alanları); üretimi süren sürüm sunucuda da atlanır.
 */
(function () {
  "use strict";
  const table = document.getElementById("tt-table");
  const menu = document.getElementById("tt-menu");
  const dialog = document.getElementById("tt-delete");
  const bar = document.getElementById("tt-select-bar");
  const unpublish = document.getElementById("tt-unpublish");
  if (!table || !menu || !dialog) return;
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const rows = () => Array.from(table.querySelectorAll("tr[data-tt]"));
  const free = () => rows().filter((r) => !r.dataset.ttBusy);

  function hide() { menu.hidden = true; menu.innerHTML = ""; }

  function confirmDelete(list) {
    if (!list.length) return;
    const form = dialog.querySelector("form");
    form.querySelector("[data-tt-ids]").innerHTML = list
      .map((r) => '<input type="hidden" name="ids" value="' + esc(r.dataset.tt) + '">').join("");
    const names = list.map((r) => "“" + r.dataset.ttName + "”");
    form.querySelector("[data-tt-title]").textContent = list.length === 1 ? "Sürümü sil" : list.length + " sürümü sil";
    form.querySelector("[data-tt-text]").textContent = list.length <= 4
      ? names.join(", ") + " silinecek."
      : names.slice(0, 3).join(", ") + " ve " + (list.length - 3) + " sürüm daha silinecek.";
    form.querySelector("[data-tt-go]").textContent = list.length === 1 ? "Sil" : list.length + " sürümü sil";
    dialog.showModal();
  }

  // --- seçerek silme ---------------------------------------------------------------------------
  function boxes() { return Array.from(table.querySelectorAll(".tt-check input")); }
  function syncBar() {
    const n = boxes().filter((b) => b.checked).length;
    bar.querySelector("[data-tt-count]").textContent = n;
    bar.querySelector("[data-tt-delete-selected]").disabled = n === 0;
  }
  function selectMode(on, first) {
    table.querySelectorAll(".tt-check").forEach((c) => { c.hidden = !on; });
    bar.hidden = !on;
    boxes().forEach((b) => { b.checked = on && first != null && b.value === String(first) && !b.disabled; });
    syncBar();
  }
  table.addEventListener("change", (e) => { if (e.target.closest(".tt-check")) syncBar(); });
  bar.querySelector("[data-tt-all]").addEventListener("click", () => {
    const all = boxes().filter((b) => !b.disabled);
    const on = all.some((b) => !b.checked);
    all.forEach((b) => { b.checked = on; });
    syncBar();
  });
  bar.querySelector("[data-tt-cancel]").addEventListener("click", () => selectMode(false));
  bar.querySelector("[data-tt-delete-selected]").addEventListener("click", () => {
    const chosen = new Set(boxes().filter((b) => b.checked).map((b) => b.value));
    confirmDelete(rows().filter((r) => chosen.has(r.dataset.tt)));
  });

  // --- menü ------------------------------------------------------------------------------------
  function itemsFor(row) {
    const busy = !!row.dataset.ttBusy;
    const others = free().length;
    return [
      { label: "Aç", run: () => { location.href = row.dataset.ttOpen; } },
      ...(row.dataset.ttPublished && unpublish ? [{ label: "Yayından kaldır…", run: () => {
        if (window.confirm("“" + row.dataset.ttName + "” yayından kaldırılsın mı? Öğrenci/öğretmen yayını, vekâlet ve nöbet hiçbir sürüme bağlı kalmaz.")) unpublish.submit();
      } }] : []),
      { sep: true },
      { label: busy ? "Sil (üretim sürüyor)" : "Sil…", run: () => confirmDelete([row]), cls: "danger", disabled: busy },
      { label: "Seçerek sil…", run: () => selectMode(true, busy ? null : row.dataset.tt) },
      { label: "Tüm sürümleri sil… (" + others + ")", run: () => confirmDelete(free()), cls: "danger", disabled: !others },
    ];
  }

  function show(row, x, y) {
    const ul = document.createElement("ul");
    ul.className = "ctx-list";
    ul.innerHTML = '<li class="ctx-head">' + esc(row.dataset.ttName) + "</li>";
    itemsFor(row).forEach((it) => {
      const li = document.createElement("li");
      if (it.sep) { li.className = "ctx-sep"; ul.appendChild(li); return; }
      li.className = "ctx-item" + (it.cls ? " " + it.cls : "") + (it.disabled ? " disabled" : "");
      li.innerHTML = "<span>" + esc(it.label) + "</span>";
      if (!it.disabled) li.addEventListener("click", () => { hide(); it.run(); });
      ul.appendChild(li);
    });
    menu.innerHTML = "";
    menu.appendChild(ul);
    menu.hidden = false;
    const w = menu.offsetWidth, h = menu.offsetHeight;
    menu.style.left = Math.max(4, Math.min(x, window.innerWidth - w - 4)) + "px";
    menu.style.top = Math.max(4, Math.min(y, window.innerHeight - h - 4)) + "px";
  }

  table.addEventListener("contextmenu", (e) => {
    const row = e.target.closest("tr[data-tt]");
    if (!row || e.target.closest(".tt-check")) return;
    e.preventDefault();
    show(row, e.clientX, e.clientY);
  });

  // Telefonda uzun basma (iOS Safari sağ tık olayı göndermez); basılı tutup bırakınca bağlantı açılmaz.
  let timer = null, opened = false, start = null;
  table.addEventListener("touchstart", (e) => {
    const row = e.target.closest("tr[data-tt]");
    if (!row || e.touches.length !== 1 || e.target.closest(".tt-check, [data-tt-button]")) return;
    const t = e.touches[0];
    start = { x: t.clientX, y: t.clientY };
    opened = false;
    timer = setTimeout(() => { opened = true; show(row, start.x, start.y); }, 550);
  }, { passive: true });
  table.addEventListener("touchmove", (e) => {
    if (!timer || !start) return;
    const t = e.touches[0];
    if (Math.abs(t.clientX - start.x) > 10 || Math.abs(t.clientY - start.y) > 10) { clearTimeout(timer); timer = null; }
  }, { passive: true });
  table.addEventListener("touchend", (e) => {
    clearTimeout(timer);
    timer = null;
    if (opened) { e.preventDefault(); opened = false; }
  });

  document.addEventListener("click", (e) => {
    const button = e.target.closest("[data-tt-button]");
    if (button) {
      e.preventDefault();
      e.stopPropagation();
      const r = button.getBoundingClientRect();
      show(button.closest("tr[data-tt]"), r.left - 160, r.bottom + 4);
      return;
    }
    if (!menu.hidden && !menu.contains(e.target)) hide();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
  window.addEventListener("scroll", hide, { passive: true });
  dialog.querySelectorAll("[data-tt-close]").forEach((b) => b.addEventListener("click", () => dialog.close()));
})();
