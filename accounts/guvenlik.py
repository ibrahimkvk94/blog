"""Giriş güvenliği: hatalı deneme kilidi ve internetten (Tailscale Funnel) erişim kuralları.

- Aynı kullanıcı adıyla art arda hatalı giriş (parola ya da iki adımlı doğrulama kodu) sınırı aşınca o kullanıcı adı
  bir süre kilitlenir (GuvenlikAyari). Sayaç önbellekte tutulur; sunucu yeniden başlarsa sıfırlanır.
- İstek dış adresten (settings.DIS_ADRESLER ya da *.ts.net) geliyorsa "dış erişim" sayılır; ayar açıksa dışarıdan
  yalnızca iki adımlı doğrulaması açık kullanıcılar girebilir. Kurum ağından giriş bundan etkilenmez.
"""

import time
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache


def _anahtar(kullanici_adi):
    return f"giris_hata:{(kullanici_adi or '').strip().casefold()}"


def kilit_kalan_dk(kullanici_adi):
    """Kullanıcı adı kilitliyse kalan dakika (en az 1), değilse 0."""
    from .models import GuvenlikAyari

    ayar = GuvenlikAyari.al()
    kayit = cache.get(_anahtar(kullanici_adi))
    if not kayit or kayit["sayi"] < ayar.giris_deneme_siniri:
        return 0
    kalan = kayit["bitis"] - time.time()
    return max(1, int(kalan // 60) + 1) if kalan > 0 else 0


def hatali_deneme(kullanici_adi):
    from .models import GuvenlikAyari

    if not kullanici_adi:
        return
    ayar = GuvenlikAyari.al()
    sure = ayar.kilit_suresi_dk * 60
    kayit = cache.get(_anahtar(kullanici_adi)) or {"sayi": 0}
    kayit["sayi"] += 1
    kayit["bitis"] = time.time() + sure
    cache.set(_anahtar(kullanici_adi), kayit, sure)


def basarili_giris(kullanici_adi):
    cache.delete(_anahtar(kullanici_adi))


def dis_erisim_mi(request):
    """İstek internetten (Funnel adresinden) mi geldi?"""
    host = request.get_host().split(":")[0].lower()
    dis = {(urlparse(a).hostname or "").lower() for a in getattr(settings, "DIS_ADRESLER", [])}
    return host in dis or host.endswith(".ts.net")


def dis_erisimde_iki_adim_gerekli(request):
    from .models import GuvenlikAyari

    return dis_erisim_mi(request) and GuvenlikAyari.al().dis_erisimde_iki_adim_zorunlu
