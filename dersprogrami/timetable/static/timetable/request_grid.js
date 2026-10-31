// Müsaitlik isteği ızgarası (İsteklerim ve bölüm mazeret ekranı): hücreye tıkla → gelebilir / gelemez / tercih etmez.
(function () {
  const form = document.getElementById("rq-form");
  if (!form) return;
  const order = ["", "no", "maybe"];
  const cells = [...form.querySelectorAll(".rq-edit button.av-cell")];
  const paint = (b) => {
    const input = b.nextElementSibling, state = input.value, changed = state !== b.dataset.current;
    b.className = "av-cell" + (state ? " av-" + state : "") + (changed ? " rq-changed" : "");
    b.textContent = changed && !state ? "✓" : state === "maybe" ? "?" : "";
  };
  const count = () => {
    const n = cells.filter((b) => b.nextElementSibling.value !== b.dataset.current).length;
    form.querySelector("[data-rq-count]").textContent = n ? n + " saat değişti" : "Kayıtlı müsaitliğinizle aynı";
  };
  cells.forEach((b) => b.addEventListener("click", () => {
    const input = b.nextElementSibling;
    input.value = order[(order.indexOf(input.value) + 1) % order.length];
    paint(b); count();
  }));
  form.querySelector("[data-rq-reset]").addEventListener("click", () => {
    cells.forEach((b) => { b.nextElementSibling.value = b.dataset.current; paint(b); });
    count();
  });
  count();
})();
