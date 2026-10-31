/* Öğretmen bilgileri toplu düzenleme: seçim, seçilenlere uygula, Excel'den yapıştır, arama / süzme. */
(function () {
  "use strict";
  const form = document.getElementById("ti-form");
  if (!form) return;
  const $ = (s, root) => (root || document).querySelector(s);
  const $$ = (s, root) => [...(root || document).querySelectorAll(s)];
  const rows = $$("[data-ti-row]", form);
  const fold = (s) => (s || "").toLocaleLowerCase("tr").replace(/\s+/g, " ").trim();
  const field = (row, name) => $(`[data-ti-field="${name}"]`, row);

  // değişen hücreler
  $$("[data-ti-field]", form).forEach((input) => { input.dataset.orig = input.value; });
  function mark(input) {
    if (input.dataset.tiField === "tc_no") input.value = input.value.replace(/\D/g, "").slice(0, 11);
    input.classList.toggle("ti-changed", input.value.trim() !== input.dataset.orig);
    input.classList.toggle("ti-bad", input.dataset.tiField === "tc_no" && input.value !== "" && input.value.length !== 11);
  }
  function refreshDirty() {
    const n = rows.filter((r) => $(".ti-changed", r)).length;
    const bad = $$(".ti-bad", form).length;
    $("[data-ti-dirty]").textContent = (n ? `${n} öğretmende kaydedilmemiş değişiklik` : "Değişiklik yok") +
      (bad ? ` · ${bad} hatalı TC (11 hane olmalı)` : "");
  }
  form.addEventListener("input", (e) => { if (e.target.dataset.tiField) { mark(e.target); refreshDirty(); } });
  form.addEventListener("submit", (e) => {
    if ($(".ti-bad", form)) { e.preventDefault(); $(".ti-bad", form).focus(); alert("TC kimlik no 11 haneli olmalı."); }
    else window.onbeforeunload = null;
  });
  window.onbeforeunload = () => ($(".ti-changed", form) ? true : undefined);

  // seçim
  const all = $("[data-ti-all]");
  const visible = () => rows.filter((r) => !r.hidden);
  const selected = () => rows.filter((r) => !r.hidden && $("[data-ti-select]", r).checked);
  function refreshSelection() {
    const n = selected().length, v = visible();
    $("[data-ti-count]").textContent = n ? `${n} öğretmen seçili` : "Seçili öğretmen yok";
    $("[data-ti-apply]").disabled = !n;
    all.checked = v.length > 0 && v.every((r) => $("[data-ti-select]", r).checked);
    all.indeterminate = !all.checked && v.some((r) => $("[data-ti-select]", r).checked);
    rows.forEach((r) => r.classList.toggle("ti-selected", $("[data-ti-select]", r).checked));
  }
  all.addEventListener("change", () => { visible().forEach((r) => { $("[data-ti-select]", r).checked = all.checked; }); refreshSelection(); });
  form.addEventListener("change", (e) => { if (e.target.matches("[data-ti-select]")) refreshSelection(); });
  // satıra tıklayınca (hücre dışında) seç
  form.addEventListener("click", (e) => {
    const row = e.target.closest("[data-ti-row]");
    if (!row || e.target.closest("input, a, button")) return;
    const box = $("[data-ti-select]", row);
    box.checked = !box.checked;
    refreshSelection();
  });

  function setValue(input, value) { input.value = value; mark(input); }
  const bulk = $$("[data-ti-bulk]");
  $("[data-ti-apply]").addEventListener("click", () => {
    const erase = (name) => $(`[data-ti-erase="${name}"]`).checked;
    const values = bulk.filter((b) => b.value.trim() || erase(b.dataset.tiBulk))
      .map((b) => [b.dataset.tiBulk, erase(b.dataset.tiBulk) ? "" : b.value.trim()]);
    if (!values.length) { alert("Önce bölüm, ünvan ya da branştan en az birini yazın (ya da “boşalt”ı işaretleyin)."); return; }
    if (values.some(([, v]) => v === "") && !confirm(`${selected().length} öğretmende işaretli alanlar boşaltılsın mı? (Kaydet'e basınca yazılır)`)) return;
    selected().forEach((r) => values.forEach(([name, v]) => setValue(field(r, name), v)));
    refreshDirty();
  });
  // arama ve süzme
  const search = $("[data-ti-search]"), filter = $("[data-ti-filter]");
  function applyFilter() {
    const q = fold(search.value), f = filter.value;
    rows.forEach((r) => {
      const text = fold(r.dataset.keys + " " + $$("[data-ti-field]", r).map((i) => i.value).join(" "));
      let ok = !q || text.includes(q);
      if (ok && f === "changed") ok = !!$(".ti-changed", r);
      else if (ok && f === "tc") ok = !field(r, "tc_no").value;
      else if (ok && f) ok = !field(r, f).value.trim();
      r.hidden = !ok;
    });
    $("[data-ti-visible]").textContent = `${visible().length} / ${rows.length} öğretmen`;
    refreshSelection();
  }
  search.addEventListener("input", applyFilter);
  filter.addEventListener("change", applyFilter);

  // Excel'den yapıştır
  const HEADERS = {
    tc_no: ["tc", "tc kimlik", "tc kimlik no", "tc no", "tckn", "kimlik no"],
    department: ["bölüm", "bolum"],
    title: ["ünvan", "unvan", "rütbe", "rutbe", "ünvan / rütbe", "ünvan/rütbe", "unvan / rutbe"],
    branch: ["branş", "brans"],
    teacher: ["öğretmen", "ogretmen", "ad soyad", "adı soyadı", "ad", "kısa ad", "isim", "öğretim elemanı"],
  };
  const index = new Map();
  rows.forEach((r) => r.dataset.keys.split("|").forEach((k) => { k = fold(k); if (k && !index.has(k)) index.set(k, r); }));
  function headerOf(cell) {
    const c = fold(cell);
    return Object.keys(HEADERS).find((k) => HEADERS[k].includes(c));
  }
  $("[data-ti-paste-go]").addEventListener("click", () => {
    const lines = $("[data-ti-paste]").value.split(/\r?\n/).filter((l) => l.trim());
    const out = $("[data-ti-paste-result]");
    if (!lines.length) { out.textContent = "Yapıştırılacak satır yok."; return; }
    const split = (l) => l.split(/\t|;/).map((c) => c.trim());
    let columns = null;
    const head = split(lines[0]).map(headerOf);
    if (head.filter(Boolean).length >= 2 && head.includes("teacher")) { columns = head; lines.shift(); }
    let filled = 0;
    const unknown = [], badTc = [];
    lines.forEach((line, n) => {
      const cells = split(line);
      const cols = columns || ["teacher", "tc_no"];
      let name = cells[cols.indexOf("teacher")];
      // başlıksız iki sütun: TC solda da olabilir
      if (!columns && /^\d{11}$/.test((cells[0] || "").replace(/\D/g, "")) && cells[1] && !/\d{6}/.test(cells[1])) {
        name = cells[1]; cells[1] = cells[0];
      }
      const row = index.get(fold(name));
      if (!row) { unknown.push(name || `${n + 1}. satır`); return; }
      cols.forEach((col, i) => {
        if (!col || col === "teacher" || cells[i] === undefined || cells[i] === "") return;
        let v = cells[i];
        if (col === "tc_no") {
          v = v.split(/[.,]/)[0].replace(/\D/g, "");
          if (v.length !== 11) { badTc.push(`${name} (${cells[i]})`); return; }
        }
        setValue(field(row, col), v);
      });
      filled += 1;
    });
    refreshDirty();
    filter.value = "changed"; applyFilter();
    out.innerHTML = "";
    const parts = [`${filled} öğretmen tabloya aktarıldı (kaydetmek için Kaydet).`];
    if (unknown.length) parts.push(`Bulunamayan: ${unknown.slice(0, 8).join(", ")}${unknown.length > 8 ? ` … +${unknown.length - 8}` : ""}`);
    if (badTc.length) parts.push(`11 hane olmayan TC: ${badTc.slice(0, 5).join(", ")}`);
    parts.forEach((p, i) => { const s = document.createElement("div"); s.textContent = p; s.className = i ? "bad" : "ok"; out.appendChild(s); });
  });

  applyFilter();
  refreshDirty();
})();
