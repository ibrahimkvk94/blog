// Kimlik Kartı Okuma: canlı kamera (kart çerçevesi, kendiliğinden çekim) ve küçültülerek fotoğraf yükleme.
// Kamera görüntüsünden yalnız çerçevenin içi gönderilir; sunucu kareyi denetler (ön yüzde T.C. no, arka yüzde kod
// satırlarının kontrol haneleri), tutunca o yüz alınır. Kareler sunucuda saklanmaz.
(() => {
  const kok = document.querySelector('[data-kimlik-okuma]');
  if (!kok) return;
  const KARE = kok.dataset.kareUrl, OKU = kok.dataset.okuUrl;
  const csrf = kok.querySelector('input[name=csrfmiddlewaretoken]').value;
  const $ = s => kok.querySelector(s);
  const turSec = $('select[name=tur]'), durum = $('[data-durum]'), panel = $('[data-kamera-panel]');
  const video = $('video'), cerceve = $('[data-cerceve]'), acBtn = $('[data-kamera-ac]');
  const elleBtn = $('[data-elle]'), arkasizBtn = $('[data-arkasiz]'), kapatBtn = $('[data-kapat]');
  const form = $('form[data-okuma]');
  const ORAN = 85.6 / 54; // ID-1 kart boyutu
  let akis = null, calisiyor = false, yuz = 'on', kareler = {};

  const bekle = ms => new Promise(r => setTimeout(r, ms));
  function yaz(m, tur) {
    durum.textContent = m;
    durum.className = 'small mt-2 fw-semibold ' + ({ ok: 'text-success', hata: 'text-danger' }[tur] || 'text-secondary');
  }
  function adim(ad, hal) {
    const e = kok.querySelector(`[data-adim="${ad}"]`);
    if (e) e.className = 'badge rounded-pill ' + ({ simdi: 'text-bg-primary', tamam: 'text-bg-success' }[hal] || 'text-bg-light border');
  }

  async function istek(url, fd, sure) {
    const ac = new AbortController();
    const z = setTimeout(() => ac.abort(), sure);
    try {
      const r = await fetch(url, { method: 'POST', body: fd, signal: ac.signal, credentials: 'same-origin',
                                   headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'fetch' } });
      try { return await r.json(); } catch (e) { return { hata: `Sunucu beklenmeyen yanıt verdi (${r.status}). Oturum kapanmış olabilir; sayfayı yenileyin.` }; }
    } finally { clearTimeout(z); }
  }

  // ------------------------------------------------------------------ canlı kamera
  function kutu(w, h) {
    let cw = w * 0.9, ch = cw / ORAN;
    if (ch > h * 0.9) { ch = h * 0.9; cw = ch * ORAN; }
    return { x: (w - cw) / 2, y: (h - ch) / 2, w: cw, h: ch };
  }
  function cerceveYerlestir() {
    const w = video.videoWidth, h = video.videoHeight;
    if (!w) return;
    video.style.aspectRatio = `${w} / ${h}`;
    const k = kutu(w, h);
    Object.assign(cerceve.style, { left: `${k.x / w * 100}%`, top: `${k.y / h * 100}%`,
                                   width: `${k.w / w * 100}%`, height: `${k.h / h * 100}%` });
  }
  function kareAl(enBuyuk = 1800) {
    const w = video.videoWidth, h = video.videoHeight, k = kutu(w, h);
    const o = Math.min(1, enBuyuk / k.w);
    const c = document.createElement('canvas');
    c.width = Math.round(k.w * o); c.height = Math.round(k.h * o);
    c.getContext('2d').drawImage(video, k.x, k.y, k.w, k.h, 0, 0, c.width, c.height);
    return new Promise(r => c.toBlob(r, 'image/jpeg', 0.9));
  }

  async function ac() {
    kareler = {}; yuz = 'on';
    adim('on', 'simdi'); adim('arka', '');
    try {
      akis = await navigator.mediaDevices.getUserMedia({ audio: false,
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 3840 }, height: { ideal: 2160 } } });
    } catch (e) {
      yaz(e.name === 'NotAllowedError' ? 'Kameraya izin verilmedi. Tarayıcının site ayarlarından kamera iznini açın.'
                                       : `Kamera açılamadı: ${e.message}`, 'hata');
      return;
    }
    video.srcObject = akis;
    panel.hidden = false; acBtn.hidden = true; arkasizBtn.hidden = true;
    video.addEventListener('loadedmetadata', cerceveYerlestir, { once: true });
    await video.play().catch(() => {});
    cerceveYerlestir();
    calisiyor = true;
    yaz('Kartın ÖN yüzünü çerçeveye oturtun; okununca kendiliğinden çekilir.');
    dongu();
  }

  function kapat() {
    calisiyor = false;
    if (akis) akis.getTracks().forEach(t => t.stop());
    akis = null; video.srcObject = null;
    panel.hidden = true; acBtn.hidden = false;
  }

  async function yuzAlindi(blob) {
    kareler[yuz] = blob;
    adim(yuz, 'tamam');
    cerceve.classList.add('tamam');
    if (yuz === 'on') {
      yuz = 'arka';
      adim('arka', 'simdi');
      arkasizBtn.hidden = false;
      yaz('Ön yüz alındı ✓  Şimdi kartı çevirin: ARKA yüz (alttaki 3 satırlık kod).', 'ok');
      await bekle(1800);
      cerceve.classList.remove('tamam');
      return false;
    }
    return true;
  }

  async function dongu() {
    while (calisiyor) {
      if (!video.videoWidth) { await bekle(200); continue; }
      cerceveYerlestir();
      const blob = await kareAl();
      const fd = new FormData();
      fd.append('kare', blob, `${yuz}.jpg`);
      fd.append('yuz', yuz);
      let j;
      try { j = await istek(KARE, fd, 25000); } catch (e) { yaz('Bağlantı yavaş, yeniden deneniyor…'); await bekle(800); continue; }
      if (!calisiyor) return;
      if (j.dur || j.hata) { yaz(j.mesaj || j.hata, 'hata'); kapat(); return; }
      if (j.uygun) {
        if (await yuzAlindi(blob)) { await bitir(); return; }
        continue;
      }
      yaz(j.mesaj || 'Bekleniyor…');
      await bekle(250);
    }
  }

  async function bitir() {
    kapat();
    acBtn.disabled = true;
    yaz('Kart okunuyor, birkaç saniye sürer…');
    const fd = new FormData();
    if (kareler.on) fd.append('on', kareler.on, 'on.jpg');
    if (kareler.arka) fd.append('arka', kareler.arka, 'arka.jpg');
    fd.append('tur', turSec.value);
    await gonder(fd);
    acBtn.disabled = false;
  }

  async function gonder(fd) {
    try {
      const j = await istek(OKU, fd, 120000);
      if (j.yonlendir) { yaz('Okundu, kontrol sayfası açılıyor…', 'ok'); location.href = j.yonlendir; return; }
      yaz(j.hata || 'Okunamadı.', 'hata');
    } catch (e) {
      yaz(e.name === 'AbortError' ? 'Zaman aşımı: bağlantı çok yavaş. Yeniden deneyin.' : `Bağlantı hatası: ${e.message}`, 'hata');
    }
  }

  if (window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    acBtn.addEventListener('click', ac);
    kapatBtn.addEventListener('click', () => { kapat(); yaz(''); });
    elleBtn.addEventListener('click', async () => {
      if (!calisiyor || !video.videoWidth) return;
      if (await yuzAlindi(await kareAl())) await bitir();
    });
    arkasizBtn.addEventListener('click', () => { if (kareler.on) bitir(); });
  } else {
    acBtn.disabled = true;
    $('[data-kamera-yok]').hidden = false;
  }

  // ------------------------------------------------------------------ fotoğraf yükleme (telefonda küçültülür)
  async function kucult(dosya, enBuyuk = 2400) {
    let kaynak;
    try {
      kaynak = await createImageBitmap(dosya, { imageOrientation: 'from-image' });
    } catch (e) {
      kaynak = await new Promise((r, h) => {
        const i = new Image();
        i.onload = () => r(i); i.onerror = h; i.src = URL.createObjectURL(dosya);
      });
    }
    const w = kaynak.width, h = kaynak.height, o = Math.min(1, enBuyuk / Math.max(w, h));
    const c = document.createElement('canvas');
    c.width = Math.round(w * o); c.height = Math.round(h * o);
    c.getContext('2d').drawImage(kaynak, 0, 0, c.width, c.height);
    return new Promise(r => c.toBlob(r, 'image/jpeg', 0.9));
  }

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const on = form.on.files[0], arka = form.arka.files[0];
    if (!on && !arka) { yaz('Önce kartın fotoğrafını çekin ya da seçin.', 'hata'); return; }
    const b = form.querySelector('button');
    b.disabled = true;
    yaz('Fotoğraflar küçültülüyor…');
    const fd = new FormData();
    for (const [ad, d] of [['on', on], ['arka', arka]]) {
      if (!d) continue;
      try { fd.append(ad, await kucult(d), `${ad}.jpg`); } catch (err) { fd.append(ad, d); }
    }
    fd.append('tur', turSec.value);
    yaz('Gönderiliyor ve okunuyor…');
    await gonder(fd);
    b.disabled = false;
  });
})();
