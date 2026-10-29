/* Hızlı git (Ctrl+K): sayfalar ve (programın içindeyken) öğretmen, sınıf, ders adı, derslik araması. */
(function () {
  "use strict";
  const dlg = document.getElementById("palette");
  if (!dlg) return;
  const input = dlg.querySelector("input");
  const list = dlg.querySelector("[data-pal-list]");
  const pages = JSON.parse(document.getElementById("palette-pages").textContent || "[]");
  const searchUrl = dlg.dataset.searchUrl;
  const icons = JSON.parse(document.getElementById("palette-icons").textContent || "{}");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const norm = (t) => String(t || "").toLocaleLowerCase("tr");
  let items = [], active = 0, timer = null, seq = 0;

  function render() {
    if (!items.length) { list.innerHTML = '<div class="pal-empty">Sonuç yok.</div>'; return; }
    let html = "", group = null;
    items.forEach((it, i) => {
      if (it.group !== group) { group = it.group; html += '<div class="pal-group">' + esc(group) + "</div>"; }
      html += '<a class="pal-item' + (i === active ? " on" : "") + '" href="' + esc(it.url) + '" data-i="' + i + '">' +
        '<span class="pal-icon">' + (icons[it.icon] || "") + "</span><span><b>" + esc(it.label) + "</b>" +
        (it.sub ? "<small>" + esc(it.sub) + "</small>" : "") + "</span></a>";
    });
    list.innerHTML = html;
    const on = list.querySelector(".pal-item.on");
    if (on) on.scrollIntoView({ block: "nearest" });
  }
  function search() {
    const q = norm(input.value.trim());
    items = pages.filter((p) => !q || norm(p.label + " " + p.group).includes(q)).map((p) => Object.assign({}, p, { group: "Sayfalar · " + p.group }));
    active = 0;
    render();
    clearTimeout(timer);
    if (!searchUrl || q.length < 2) return;
    const mine = ++seq;
    timer = setTimeout(async () => {
      try {
        const res = await (await fetch(searchUrl + "?q=" + encodeURIComponent(input.value.trim()), { headers: { "X-Requested-With": "fetch" } })).json();
        if (mine !== seq) return;
        items = items.concat(res.results.map((r) => ({ label: r.label, sub: r.sub, url: r.url, icon: r.icon, group: r.kind })));
        render();
      } catch (e) { /* arama olmadan da sayfalar çalışır */ }
    }, 150);
  }
  function open() {
    input.value = "";
    search();
    dlg.showModal();
    input.focus();
  }
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); dlg.open ? dlg.close() : open(); }
  });
  document.querySelectorAll("[data-palette-open]").forEach((b) => b.addEventListener("click", open));
  input.addEventListener("input", search);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!items.length) return;
      active = (active + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
      render();
    } else if (e.key === "Enter" && items[active]) {
      e.preventDefault();
      location.href = items[active].url;
    }
  });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
})();
