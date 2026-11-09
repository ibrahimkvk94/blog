/* Menü yıldızları: sayfayı kısayollara ekler / çıkarır (POST core:kisayol_degistir). Menünün Kısayollar bölümü
   sunucudan gelen HTML ile yenilenir; ağaçtaki aynı sayfanın yıldızı da güncellenir. Sayfa yenilenmez. */
(function () {
  "use strict";
  const menu = document.querySelector(".kenar-menu");
  if (!menu) return;
  const token = () => (document.querySelector("[name=csrfmiddlewaretoken]") || {}).value || "";

  function isaretle(pk, dolu) {
    menu.querySelectorAll(`.menu-yildiz[data-birim="${pk}"]`).forEach((b) => {
      b.classList.toggle("dolu", dolu);
      b.setAttribute("aria-pressed", dolu ? "true" : "false");
      b.title = dolu ? "Kısayollardan çıkar" : "Kısayollara ekle";
      const ad = (b.getAttribute("aria-label") || "").split(":")[0];
      b.setAttribute("aria-label", `${ad}: ${dolu ? "kısayollardan çıkar" : "kısayollara ekle"}`);
      const i = b.querySelector("i");
      if (i) i.className = "bi " + (dolu ? "bi-star-fill" : "bi-star");
    });
  }

  menu.addEventListener("click", async (e) => {
    const b = e.target.closest(".menu-yildiz");
    if (!b) return;
    e.preventDefault();
    e.stopPropagation();
    const pk = b.dataset.birim;
    b.classList.add("bekliyor");
    try {
      const adres = (document.getElementById("kisayolBolumu") || {}).dataset?.url || "/kisayol/0/";
      const r = await fetch(adres.replace(/\/0\/$/, `/${pk}/`), {
        method: "POST", credentials: "same-origin",
        headers: { "X-CSRFToken": token(), "X-Requested-With": "fetch" },
      });
      if (!r.ok) throw new Error(r.status);
      const veri = await r.json();
      const bolum = document.getElementById("kisayolBolumu");
      if (bolum) bolum.innerHTML = veri.html;
      isaretle(pk, veri.yildizli);
    } catch (hata) {
      b.title = "Kaydedilemedi; sayfayı yenileyip tekrar deneyin.";
    } finally {
      menu.querySelectorAll(".menu-yildiz.bekliyor").forEach((x) => x.classList.remove("bekliyor"));
    }
  });
})();
