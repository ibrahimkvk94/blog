/* Kayıt düzenleyici: sekmeler, kaydedilmemiş değişiklik takibi, sayfadan çıkmadan kaydetme (alan hataları
 * yerinde gösterilir), kayıt listesinde arama ve önceki/sonraki kayda geçiş. data.js'ten sonra yüklenir. */
(function () {
  "use strict";
  const root = document.querySelector("[data-editor]");
  if (!root) return;
  const $ = (sel, el) => (el || document).querySelector(sel);
  const $$ = (sel, el) => Array.from((el || document).querySelectorAll(sel));
  const form = document.getElementById(root.dataset.form);
  const state = $("[data-state]", root);
  const revert = $("[data-revert]", root);

  function toast(message, kind) {
    const t = document.createElement("div");
    t.className = "toast" + (kind === "error" ? " error" : kind === "ok" ? " ok" : "");
    t.textContent = message;
    $("#toasts").appendChild(t);
    setTimeout(() => t.remove(), 4200);
  }

  // ---- sekmeler --------------------------------------------------------------------------------
  const tabs = $$("[data-tab]", root);
  function showTab(key) {
    if (!tabs.length) return;
    if (!tabs.some((t) => t.dataset.tab === key)) key = tabs[0].dataset.tab;
    tabs.forEach((t) => { const on = t.dataset.tab === key; t.classList.toggle("active", on); t.setAttribute("aria-selected", on); });
    $$("[data-tab-panel]").forEach((p) => { p.hidden = p.dataset.tabPanel !== key; });
    if (location.hash !== "#" + key) history.replaceState(null, "", "#" + key);
  }
  tabs.forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  const firstError = tabs.find((t) => t.classList.contains("has-error"));
  showTab(firstError ? firstError.dataset.tab : location.hash.slice(1));

  // ---- kaydedilmemiş değişiklik ----------------------------------------------------------------
  const snapshot = () => {
    const data = new FormData(form);
    data.delete("csrfmiddlewaretoken");
    return JSON.stringify([...data.entries()].filter(([, v]) => typeof v === "string"));
  };
  let baseline = "";
  let dirty = false;
  let saving = false;
  function setState(kind, text) {
    state.className = "rec-state " + kind;
    $("span", state).textContent = text;
  }
  function check() {
    if (saving) return;
    dirty = snapshot() !== baseline;
    revert.hidden = !dirty;
    if (dirty && !state.classList.contains("error")) setState("dirty", "Kaydedilmemiş değişiklikler");
    else if (!state.classList.contains("error")) setState("clean", state.dataset.saved || "Kaydedildi");
  }
  let timer;
  const later = () => { clearTimeout(timer); timer = setTimeout(check, 60); };
  // Izgara ve çip seçimleri gizli alanları tıklamayla değiştirir: input/change/click hepsinde denetle.
  ["input", "change", "click"].forEach((ev) => form.addEventListener(ev, later));
  root.addEventListener("click", later);
  setTimeout(() => { baseline = snapshot(); state.dataset.saved = form.querySelector("[name]") && !$("[data-rec-title]").textContent.trim().startsWith("Yeni") ? "Kaydedildi" : "Yeni kayıt"; check(); }, 0);
  window.addEventListener("beforeunload", (e) => { if (dirty && !saving) { e.preventDefault(); e.returnValue = ""; } });
  revert.addEventListener("click", () => { if (confirm("Kaydedilmemiş değişiklikler geri alınsın mı?")) { dirty = false; location.reload(); } });

  // ---- alan hataları ---------------------------------------------------------------------------
  function clearErrors() {
    $$(".form-row.has-error", form).forEach((r) => r.classList.remove("has-error"));
    $$(".error[data-live]", form).forEach((e) => e.remove());
    tabs.forEach((t) => t.classList.remove("has-error"));
    const nf = $("[data-non-field]", form);
    if (nf) { nf.hidden = true; nf.textContent = ""; }
  }
  function showErrors(data) {
    let first = null;
    Object.entries(data.errors || {}).forEach(([name, messages]) => {
      const input = form.querySelector('[name="' + name + '"]');
      const row = input && input.closest(".form-row");
      if (!row) { (data.non_field = data.non_field || []).push(messages.join(" ")); return; }
      row.classList.add("has-error");
      messages.forEach((m) => { const d = document.createElement("div"); d.className = "error"; d.dataset.live = ""; d.textContent = m; row.appendChild(d); });
      const panel = row.closest("[data-tab-panel]");
      if (panel) { const tab = tabs.find((t) => t.dataset.tab === panel.dataset.tabPanel); if (tab) tab.classList.add("has-error"); }
      first = first || row;
    });
    const nf = $("[data-non-field]", form);
    if (nf && (data.non_field || []).length) { nf.textContent = data.non_field.join(" "); nf.hidden = false; first = first || nf; }
    if (first) {
      const panel = first.closest("[data-tab-panel]");
      if (panel) showTab(panel.dataset.tabPanel);
      first.scrollIntoView({ block: "center", behavior: "smooth" });
      const input = first.querySelector("input:not([type=hidden]), select, textarea");
      if (input) input.focus({ preventScroll: true });
    }
  }

  // Müsaitlik değişikliği aktif programda dersleri kapalı saate düşürdüyse sunucunun hazırladığı uyarı
  // ("En az değişiklikle onar" düğmesiyle) düzenleyicinin üstünde gösterilir; kapatılana kadar durur.
  function showAvailabilityAlert(html) {
    if (!html) return;
    let box = document.querySelector("[data-av-alert-box]");
    if (!box) {
      box = document.createElement("div");
      box.className = "alert alert-warning av-alert-box";
      box.dataset.avAlertBox = "";
      root.parentNode.insertBefore(box, root);
    }
    box.innerHTML = html + '<button type="button" class="av-alert-close" title="Kapat" aria-label="Kapat">×</button>';
    box.querySelector(".av-alert-close").addEventListener("click", () => box.remove());
    box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  // ---- kaydet ----------------------------------------------------------------------------------
  async function save(submitter) {
    if (saving) return;
    saving = true;
    setState("saving", "Kaydediliyor…");
    const body = new FormData(form);
    if (submitter && submitter.name) body.set(submitter.name, submitter.value);
    let res, data;
    try {
      res = await fetch(location.pathname + location.search, { method: "POST", body, credentials: "same-origin", headers: { "X-Requested-With": "fetch" } });
      data = await res.json();
    } catch (e) {
      saving = false;
      setState("error", "Kaydedilemedi");
      toast("Sunucuya ulaşılamadı; değişiklikleriniz duruyor, tekrar deneyin.", "error");
      return;
    }
    saving = false;
    clearErrors();
    const conflictBox = $("[data-conflict]", form);
    if (data.conflict && conflictBox) {
      // Kayıt bu sayfa açıldıktan sonra başkası tarafından değişti: farklı alanlar gösterilir, "Yine de kaydet" sorulur.
      conflictBox.innerHTML = data.html || "";
      setState("error", "Kayıt siz düzenlerken değişti");
      toast(data.message || "Kayıt siz düzenlerken değişti.", "error");
      conflictBox.scrollIntoView({ block: "center", behavior: "smooth" });
      return;
    }
    if (conflictBox) conflictBox.innerHTML = "";
    if (!data.ok) {
      setState("error", "Hatalı alanlar var");
      toast(data.message || "Kaydedilemedi.", "error");
      showErrors(data);
      return;
    }
    dirty = false;
    if (data.next) { location.href = data.next; return; }
    if (data.reload) { location.href = data.url + location.hash; return; }
    const token = $("[data-record-state]", form);
    if (token && data.state) token.value = data.state;  // kaydedilen hal yeni karşılaştırma noktası
    baseline = snapshot();
    state.dataset.saved = "Kaydedildi · " + new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
    state.classList.remove("error");
    check();
    toast(data.message, "ok");
    showAvailabilityAlert(data.alert);
    if (data.title) $("[data-rec-title]").textContent = data.title;
    $("[data-rec-sub]").textContent = data.sub || "";
    const item = $(".rec-item.active", root);
    if (item) {
      $(".rec-item-label", item).textContent = data.title || "";
      let sub = $(".rec-item-sub", item);
      if (!sub && data.sub) { sub = document.createElement("span"); sub.className = "rec-item-sub"; item.appendChild(sub); }
      if (sub) sub.textContent = data.sub || "";
    }
    // Müsaitliği uygulanan diğer kayıtlar bir kez kopyalandı: seçimleri temizle (ikinci kayıtta yinelenmesin).
    $$("[data-target-picker] input[type=checkbox]:checked", form).forEach((c) => { c.checked = false; c.dispatchEvent(new Event("change", { bubbles: true })); });
    baseline = snapshot();
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); save(e.submitter); });
  // Çakışma kutusundaki "Güncel hali yükle": değişiklikler bilerek bırakılıyor, ayrıca sorulmaz.
  form.addEventListener("click", (e) => { if (e.target.closest("[data-conflict-reload]")) dirty = false; });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(null); }
    if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
      const link = $(e.key === "ArrowUp" ? "[data-nav-prev]" : "[data-nav-next]", root);
      if (link && !link.classList.contains("is-disabled")) { e.preventDefault(); link.click(); }
    }
  });

  // ---- kayıt listesi ---------------------------------------------------------------------------
  const search = $("[data-nav-search]", root);
  const items = $$("[data-nav-item]", root);
  const none = $("[data-nav-none]", root);
  const norm = (t) => t.toLocaleLowerCase("tr").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/ı/g, "i");
  items.forEach((i) => { i.dataset.q = norm(i.textContent); });
  if (search) search.addEventListener("input", () => {
    const q = norm(search.value.trim());
    let shown = 0;
    items.forEach((i) => { i.hidden = q && !i.dataset.q.includes(q); if (!i.hidden) shown++; });
    none.hidden = shown > 0 || !items.length;
  });
  if (search) search.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); const first = $$("[data-nav-item]", root).find((i) => !i.hidden); if (first) first.click(); }
  });
  root.addEventListener("click", (e) => {  // sıralama değişince düğmeler etkin/edilgin olabilir: tıklama anında bakılır
    const link = e.target.closest(".is-disabled");
    if (link) e.preventDefault();
  }, true);
  // Sıralama: kayıt listesi seçilen sıraya dizilir; önceki/sonraki kayıt ve "3 / 40" konumu bu sırayı izler.
  const sortSelect = $("[data-nav-sort]", root);
  if (sortSelect && window.DataSort) {
    const list = $("[data-nav-list]", root);
    const prev = $("[data-nav-prev]", root), next = $("[data-nav-next]", root), pos = $("[data-nav-pos]", root);
    const setLink = (a, item) => {
      if (!a) return;
      a.setAttribute("href", item ? item.getAttribute("href") : "#");
      a.classList.toggle("is-disabled", !item);
    };
    window.DataSort.bind(sortSelect, list, () => items, (sorted) => {
      const i = sorted.findIndex((el) => el.classList.contains("active"));
      if (i < 0) return;
      setLink(prev, sorted[i - 1]);
      setLink(next, sorted[i + 1]);
      if (pos) pos.textContent = (i + 1) + " / " + sorted.length;
    });
  }
  const active = $(".rec-item.active", root);
  if (active) {  // yalnızca listeyi kaydır (sayfa yerinde kalsın)
    const list = $("[data-nav-list]", root);
    list.scrollTop = active.offsetTop - list.offsetTop - list.clientHeight / 2 + active.offsetHeight / 2;
  }
  // Başka kayda geçerken: kaydedilmemiş değişiklik varsa sor; sekme korunur.
  root.addEventListener("click", (e) => {
    const link = e.target.closest("[data-nav-item], [data-nav-prev], [data-nav-next]");
    if (!link || link.classList.contains("is-disabled") || e.ctrlKey || e.metaKey) return;
    if (dirty && !confirm("Kaydedilmemiş değişiklikler var. Kaydetmeden geçilsin mi?")) { e.preventDefault(); return; }
    dirty = false;
    if (location.hash) { e.preventDefault(); location.href = link.getAttribute("href") + location.hash; }
  });
})();
