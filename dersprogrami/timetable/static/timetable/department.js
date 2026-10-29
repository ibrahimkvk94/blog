// Bölüm ders dağılımı: ders başına öğretmen + kısım satırları, kısım toplamı denetimi ve öğretmen yükleri (canlı).
(function () {
  const form = document.getElementById("dp-form");
  if (!form) return;
  const teachers = JSON.parse(document.getElementById("dp-teachers").textContent);
  const names = Object.fromEntries(teachers.map((t) => [String(t.id), t.name]));

  function fill(select) {
    const value = select.dataset.value || select.value;
    const groups = {};
    teachers.forEach((t) => { (groups[t.group] = groups[t.group] || []).push(t); });
    select.innerHTML = '<option value="">— öğretmen seçin —</option>' + Object.entries(groups).map(([g, list]) =>
      '<optgroup label="' + g + '">' + list.map((t) => '<option value="' + t.id + '">' + t.name.replace(/</g, "&lt;") + "</option>").join("") + "</optgroup>").join("");
    select.value = value;
  }

  function update() {
    const inside = {};
    let problems = 0;
    form.querySelectorAll(".dp-subject").forEach((section) => {
      const sections = +section.dataset.sections, hours = +section.dataset.hours;
      let total = 0;
      const seen = new Set();
      section.querySelectorAll(".dp-row").forEach((row) => {
        const t = row.querySelector("select").value, n = +row.querySelector("input").value || 0;
        row.querySelector(".dp-hours").textContent = n ? n * hours + " saat" : "";
        row.classList.toggle("dup", !!t && seen.has(t));
        if (t) { seen.add(t); total += n; inside[t] = (inside[t] || 0) + n * hours; }
      });
      const state = section.querySelector("[data-dp-state]");
      const ok = total === sections && sections > 0;
      state.className = "pill " + (ok ? "ok" : total > sections ? "error" : "warn");
      state.textContent = ok ? sections + "/" + sections + " kısım" : total > sections ? total + "/" + sections + " · " + (total - sections) + " fazla" : total + "/" + sections + " · " + (sections - total) + " eksik";
      if (!ok) problems += 1;
    });
    const body = form.querySelector(".dp-loads tbody");
    Object.keys(inside).forEach((t) => {
      if (!body.querySelector('[data-dp-load="' + t + '"]')) {
        const tr = document.createElement("tr");
        tr.dataset.dpLoad = t; tr.dataset.outside = "0"; tr.dataset.target = "";
        tr.innerHTML = "<td></td><td class='num' data-in></td><td class='num'>0</td><td class='num'><b data-total></b></td>";
        tr.firstChild.textContent = names[t] || t;
        body.appendChild(tr);
      }
    });
    body.querySelectorAll("tr").forEach((tr) => {
      const n = inside[tr.dataset.dpLoad] || 0, total = n + (+tr.dataset.outside || 0);
      tr.querySelector("[data-in]").textContent = n;
      tr.querySelector("[data-total]").textContent = total;
      tr.classList.toggle("over", !!tr.dataset.target && total > +tr.dataset.target);
    });
    const summary = form.querySelector("[data-dp-summary]");
    if (summary) summary.textContent = problems ? problems + " derste kısım toplamı tutmuyor; yine de gönderebilirsiniz, program sorumlusu görür." : "Bütün derslerin kısımları dağıtıldı.";
  }

  form.querySelectorAll(".dp-row select").forEach(fill);
  form.addEventListener("input", update);
  form.addEventListener("change", update);
  form.addEventListener("click", (e) => {
    const add = e.target.closest("[data-dp-add]");
    if (add) {
      const rows = form.querySelector('[data-dp-rows="' + add.dataset.dpAdd + '"]');
      const row = document.createElement("div");
      row.className = "dp-row";
      row.innerHTML = '<select class="select select-sm" name="t-' + add.dataset.dpAdd + '"></select>' +
        '<input class="input input-sm" type="number" min="0" name="n-' + add.dataset.dpAdd + '" value="1" aria-label="Kısım">' +
        '<span class="dp-hours"></span><button type="button" class="btn btn-sm btn-ghost" data-dp-remove aria-label="Satırı sil">✕</button>';
      rows.appendChild(row);
      fill(row.querySelector("select"));
      row.querySelector("select").focus();
      update();
    }
    const remove = e.target.closest("[data-dp-remove]");
    if (remove) { remove.closest(".dp-row").remove(); update(); }
  });
  update();
})();
