/* Kim düzenliyor: açık düzenleyici (program ya da kayıt) 30 sn'de bir ve sekmeye dönülünce sunucuya nabız
 * gönderir; son 90 sn'de görülen diğer düzenleyiciler başlıktaki rozette yazılır ("Ahmet Y. de bu programı
 * düzenliyor"). Sayfa kapanırken kayıt silinir. Program düzenleyicisi (grid.js) window.PresenceExtra ile son
 * gördüğü sürümü ekler; yanıt "presence:update" olayıyla yayınlanır (başkası değiştirdiyse tablo yenilenir).
 */
(function () {
  "use strict";
  const pill = document.querySelector("[data-presence]");
  if (!pill) return;
  const url = pill.dataset.url, key = pill.dataset.key, editing = pill.dataset.editing === "1";
  const text = pill.querySelector("[data-presence-text]");
  const POLL = 30000;
  const csrf = () => decodeURIComponent((document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || "");
  const tab = window.EditorTab || (window.EditorTab = Math.random().toString(36).slice(2, 10));

  async function beat() {
    const extra = typeof window.PresenceExtra === "function" ? (window.PresenceExtra() || {}) : {};
    let d;
    try {
      const r = await fetch(url, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify(Object.assign({ key, editing, tab }, extra)),
      });
      if (!r.ok) return;
      d = await r.json();
    } catch (e) { return; /* sunucu yeniden başlıyor olabilir: sonraki nabızda */ }
    text.textContent = d.text || "";
    pill.title = (d.others || []).length ? "Şu anda düzenleyenler: " + d.others.join(", ") + "\nAynı alanları değiştirirseniz kaydederken uyarılırsınız." : "";
    pill.hidden = !d.text;
    document.dispatchEvent(new CustomEvent("presence:update", { detail: d }));
  }

  beat();
  setInterval(beat, POLL);  // arka plandaki sekmede tarayıcı seyreltir; yine de 90 sn içinde kalır
  document.addEventListener("visibilitychange", () => { if (!document.hidden) beat(); });
  window.addEventListener("pageshow", (e) => { if (e.persisted) beat(); });
  window.addEventListener("pagehide", () => {
    if (!navigator.sendBeacon) return;
    const f = new FormData();
    f.append("key", key);
    f.append("leave", "1");
    f.append("csrfmiddlewaretoken", csrf());
    navigator.sendBeacon(url, f);
  });
})();
