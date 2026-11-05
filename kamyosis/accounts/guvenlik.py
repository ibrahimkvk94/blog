"""Giriş güvenliği: hatalı deneme kilidi ve internetten (Tailscale Funnel) erişim kuralları.

- Aynı kullanıcı adıyla art arda hatalı giriş (parola ya da iki adımlı doğrulama kodu) sınırı aşınca o kullanıcı adı
  kilitlenir; kilit her seferinde uzar: ilk kilit 1 dk, sonra 3, 9, 27 … dk (GuvenlikAyari: süre × katsayı^n).
  Başarılı giriş sayacı sıfırlar. Sayaç önbellekte 24 saat tutulur; sunucu yeniden başlarsa sıfırlanır.
- İstek dış adresten (settings.DIS_ADRESLER ya da *.ts.net) geliyorsa "dış erişim" sayılır; ayar açıksa dışarıdan
  yalnızca iki adımlı doğrulaması açık kullanıcılar girebilir. Kurum ağından giriş bundan etkilenmez.
- Geliştirme sürecinde GuvenlikAyari.gelistirme_kodu doluysa girişte herkese kod sorulur ve bu ortak kod kabul edilir
  (dış erişim kuralının yerine de geçer). Kod depoya yazılmaz; yalnızca canlı veritabanındaki ayardadır.
"""

import hmac
import time
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache


def _anahtar(kullanici_adi):
    return f"giris_hata:{(kullanici_adi or '').strip().casefold()}"


HAFIZA = 24 * 60 * 60  # kilit geçmişi bu kadar saniye tutulur (sonraki kilit daha uzun olsun diye)


def kilit_kalan_dk(kullanici_adi):
    """Kullanıcı adı kilitliyse kalan dakika (yukarı yuvarlanmış, en az 1), değilse 0."""
    kayit = cache.get(_anahtar(kullanici_adi))
    kalan = (kayit or {}).get("kilit_bitis", 0) - time.time()
    return max(1, -int(-kalan // 60)) if kalan > 0 else 0


def kilit_suresi_sn(ayar, kilit_sayisi):
    """n. kilidin süresi: ilk kilit = kilit süresi, sonrakiler katsayı kadar uzar (1, 3, 9, 27 … dk)."""
    return int(ayar.kilit_suresi_dk * 60 * ayar.kilit_katsayisi ** max(0, kilit_sayisi - 1))


def hatali_deneme(kullanici_adi):
    from .models import GuvenlikAyari

    if not kullanici_adi or kilit_kalan_dk(kullanici_adi):
        return
    ayar = GuvenlikAyari.al()
    kayit = cache.get(_anahtar(kullanici_adi)) or {"sayi": 0, "kilit_sayisi": 0, "kilit_bitis": 0}
    kayit["sayi"] += 1
    if kayit["sayi"] >= ayar.giris_deneme_siniri:
        kayit["kilit_sayisi"] += 1
        kayit["kilit_bitis"] = time.time() + kilit_suresi_sn(ayar, kayit["kilit_sayisi"])
        kayit["sayi"] = 0
    cache.set(_anahtar(kullanici_adi), kayit, max(HAFIZA, int(kayit["kilit_bitis"] - time.time()) + 60))


def basarili_giris(kullanici_adi):
    cache.delete(_anahtar(kullanici_adi))


def dis_erisim_mi(request):
    """İstek internetten (Funnel adresinden) mi geldi?"""
    host = request.get_host().split(":")[0].lower()
    dis = {(urlparse(a).hostname or "").lower() for a in getattr(settings, "DIS_ADRESLER", [])}
    return host in dis or host.endswith(".ts.net")


def _sade(kod):
    return "".join(ch for ch in str(kod or "") if ch.isdigit() or ch.isalpha())


def gelistirme_kodu():
    """Geliştirme sürecinde herkes için geçerli ortak doğrulama kodu (GuvenlikAyari); tanımlı değilse boş."""
    from .models import GuvenlikAyari

    return _sade(GuvenlikAyari.al().gelistirme_kodu)


def gelistirme_kodu_dogru(kod):
    beklenen = gelistirme_kodu()
    return bool(beklenen) and hmac.compare_digest(_sade(kod), beklenen)


def dis_erisimde_iki_adim_gerekli(request):
    from .models import GuvenlikAyari

    ayar = GuvenlikAyari.al()
    return dis_erisim_mi(request) and ayar.dis_erisimde_iki_adim_zorunlu and not _sade(ayar.gelistirme_kodu)
