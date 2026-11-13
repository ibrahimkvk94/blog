/* Program ve kurum sağ tık menüsü (Kurumlarım, kurum sayfası).
 *
 * Menü öğeleri data-pm="program" ya da data-pm="institution" taşır (kimlik, ad, kurum, açma adresi, yetki).
 * Sağ tık ya da öğedeki ⋯ düğmesi menüyü açar; seçilen işlem ortak pencerelerden birini doldurup açar. Formlar
 * mevcut sunucu işlemlerine gider (kurum sayfası düzenleme, program kopyalama, program silme). Formlarda adı
 * "action" olan alan bulunduğundan gidilecek adres setAttribute ile verilir (form.action o alanı döndürür).
 */
(function () {
  "use strict";
  const cfg = document.getElementById("pm-config");
  if (!cfg) return;
  const menu = document.getElementById("pm-menu");
  const targets = JSON.parse(document.getElementById("pm-targets").textContent || "[]");
  const url = (pattern, id) => pattern.replace("/0/", "/" + id + "/");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function hide() { menu.hidden = true; menu.innerHTML = ""; }

  function open(dialog, setup) {
    const form = dialog.querySelector("form");
    form.reset();
    setup(form);
    dialog.showModal();
    const first = form.querySelector("input:not([type=hidden]):not([type=checkbox]), select");
    if (first) { first.focus(); if (first.select) first.select(); }
  }

  function rename(item) {
    const program = item.dataset.pm === "program";
    open(document.getElementById("pm-rename"), (form) => {
      form.setAttribute("action", url(cfg.dataset.instUrl, program ? item.dataset.pmInst : item.dataset.pmId));
      form.elements.action.value = program ? "rename_program" : "rename";
      form.elements.program.value = program ? item.dataset.pmId : "";
      form.elements.next.value = cfg.dataset.next;
      form.elements.name.value = item.dataset.pmName;
      form.querySelector("[data-pm-title]").textContent = (program ? "Programı" : "Kurumu") + " yeniden adlandır";
      form.querySelector("[data-pm-label]").textContent = (program ? "Programın" : "Kurumun") + " yeni adı";
    });
  }

  function copy(item) {
    open(document.getElementById("pm-copy"), (form) => {
      form.setAttribute("action", url(cfg.dataset.copyUrl, item.dataset.pmInst));
      form.elements.source.value = item.dataset.pmId;
      form.elements.name.value = item.dataset.pmName + " (kopya)";
      form.querySelector("[data-pm-title]").textContent = "“" + item.dataset.pmName + "” programını kopyala";
    });
  }

  function move(item) {
    open(document.getElementById("pm-move"), (form) => {
      form.setAttribute("action", url(cfg.dataset.instUrl, item.dataset.pmInst));
      form.elements.program.value = item.dataset.pmId;
      form.elements.next.value = cfg.dataset.next;
      form.elements.target.innerHTML = targets.filter((t) => String(t.id) !== item.dataset.pmInst)
        .map((t) => '<option value="' + t.id + '">' + esc(t.name) + "</option>").join("");
      form.querySelector("[data-pm-title]").textContent = "“" + item.dataset.pmName + "” programını başka kuruma taşı";
    });
  }

  function remove(item) {
    const program = item.dataset.pm === "program";
    const dialog = document.getElementById("pm-delete");
    open(dialog, (form) => {
      form.setAttribute("action", program ? url(cfg.dataset.deleteUrl, item.dataset.pmId) : url(cfg.dataset.instUrl, item.dataset.pmId));
      form.elements.action.value = program ? "" : "delete";
      form.elements.next.value = cfg.dataset.next;
      form.querySelector("[data-pm-title]").textContent = "“" + item.dataset.pmName + "” " + (program ? "programını" : "kurumunu") + " sil";
      form.querySelector("[data-pm-text]").textContent = program
        ? "Sınıflar, öğretmenler, dersler, kart ilişkileri ve tüm sürümler kalıcı olarak silinir. Geri alınamaz; önce yedek almanız önerilir."
        : "Programı kalmamış kurum ve üyelikleri silinir.";
      const box = form.querySelector("[data-pm-confirm-box]"), go = form.querySelector("[data-pm-delete-go]");
      box.hidden = !program;
      go.disabled = program;
      form.elements.confirm.oninput = () => { go.disabled = form.elements.confirm.value.trim() !== item.dataset.pmName.trim(); };
      form.elements.confirm.placeholder = item.dataset.pmName;
    });
  }

  function itemsFor(item) {
    const edit = item.dataset.pmEdit === "1";
    const list = [{ label: "Aç", run: () => { location.href = item.dataset.pmOpen; } }];
    if (item.dataset.pm === "program") {
      if (edit) {
        list.push({ sep: true }, { label: "Yeniden adlandır…", run: () => rename(item) }, { label: "Kopyala…", run: () => copy(item) });
        if (targets.some((t) => String(t.id) !== item.dataset.pmInst)) list.push({ label: "Başka kuruma taşı…", run: () => move(item) });
        list.push({ sep: true }, { label: "Sil…", run: () => remove(item), cls: "danger" });
      }
    } else if (edit) {
      list.push({ sep: true }, { label: "Yeniden adlandır…", run: () => rename(item) });
      if (item.dataset.pmDeletable === "1") list.push({ sep: true }, { label: "Sil…", run: () => remove(item), cls: "danger" });
    }
    return list;
  }

  function show(item, x, y) {
    const ul = document.createElement("ul");
    ul.className = "ctx-list";
    ul.innerHTML = '<li class="ctx-head">' + esc(item.dataset.pmName) + "</li>";
    itemsFor(item).forEach((it) => {
      const li = document.createElement("li");
      if (it.sep) { li.className = "ctx-sep"; ul.appendChild(li); return; }
      li.className = "ctx-item" + (it.cls ? " " + it.cls : "");
      li.innerHTML = "<span>" + esc(it.label) + "</span>";
      li.addEventListener("click", () => { hide(); it.run(); });
      ul.appendChild(li);
    });
    menu.innerHTML = "";
    menu.appendChild(ul);
    menu.hidden = false;
    const w = menu.offsetWidth, h = menu.offsetHeight;
    menu.style.left = Math.max(4, Math.min(x, window.innerWidth - w - 4)) + "px";
    menu.style.top = Math.max(4, Math.min(y, window.innerHeight - h - 4)) + "px";
  }

  document.addEventListener("contextmenu", (e) => {
    const item = e.target.closest("[data-pm]");
    if (!item) return;
    e.preventDefault();
    show(item, e.clientX, e.clientY);
  });
  document.addEventListener("click", (e) => {
    const button = e.target.closest("[data-pm-button]");
    if (button) {
      e.preventDefault();
      e.stopPropagation();
      const r = button.getBoundingClientRect();
      show(button.closest("[data-pm]"), r.left, r.bottom + 4);
      return;
    }
    if (!menu.hidden && !menu.contains(e.target)) hide();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
  window.addEventListener("scroll", hide, { passive: true });
  document.querySelectorAll("[data-pm-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));
})();
