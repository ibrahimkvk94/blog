"""İki adımlı doğrulama (TOTP, RFC 6238): Google / Microsoft Authenticator gibi uygulamalarla 6 haneli kod.

- İsteğe bağlıdır: her kullanıcı kendi hesabında açar ya da kapatır; yönetici kaybolan telefon için sıfırlayabilir.
- Kod 30 saniyede bir değişir; saat kaymasına karşı bir önceki ve bir sonraki kod da kabul edilir. Kullanılan kod
  (zaman adımı) ikinci kez kabul edilmez.
- Telefonu kaybedene tek kullanımlık yedek kodlar verilir; veritabanında yalnızca SECRET_KEY ile imzalı özetleri
  (HMAC-SHA256) tutulur. Parola özeti (PBKDF2) kullanılmaz: her girişte 10 özeti denemek saniyeler sürerdi.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from django.conf import settings

ADIM = 30           # saniye
HANE = 6
PENCERE = 1         # ± bu kadar adım kabul edilir
YEDEK_SAYISI = 10
YAYINCI = "KAMYOSİS"


def gizli_uret():
    """160 bitlik rastgele gizli anahtar (base32, uygulamaya elle girilebilir)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _kod(gizli, adim):
    anahtar = base64.b32decode(gizli + "=" * (-len(gizli) % 8))
    ozet = hmac.new(anahtar, struct.pack(">Q", adim), hashlib.sha1).digest()
    kaydir = ozet[-1] & 0x0F
    sayi = struct.unpack(">I", ozet[kaydir:kaydir + 4])[0] & 0x7FFFFFFF
    return str(sayi % 10 ** HANE).zfill(HANE)


def simdiki_adim(zaman=None):
    return int((time.time() if zaman is None else zaman) // ADIM)


def dogrula(gizli, kod, son_adim=None, zaman=None):
    """Kod doğruysa kabul edilen zaman adımını, değilse None döner. son_adim ve öncesi (kullanılmış) reddedilir."""
    kod = "".join(ch for ch in str(kod or "") if ch.isdigit())
    if len(kod) != HANE or not gizli:
        return None
    simdi = simdiki_adim(zaman)
    for adim in range(simdi - PENCERE, simdi + PENCERE + 1):
        if son_adim is not None and adim <= son_adim:
            continue
        if hmac.compare_digest(_kod(gizli, adim), kod):
            return adim
    return None


def otpauth_adresi(gizli, hesap):
    """Authenticator uygulamasının karekoddan okuduğu adres."""
    etiket = quote(f"{YAYINCI}:{hesap}")
    return f"otpauth://totp/{etiket}?secret={gizli}&issuer={quote(YAYINCI)}&digits={HANE}&period={ADIM}"


def karekod_svg(adres):
    import segno

    return segno.make(adres, error="m").svg_inline(scale=5, dark="#0f1c33", light="#ffffff")


def _ozet(kod):
    sade = "".join(ch for ch in str(kod or "").lower() if ch.isalnum())
    return hmac.new(settings.SECRET_KEY.encode(), f"yedek:{sade}".encode(), hashlib.sha256).hexdigest()


def yedek_kodlar_uret():
    """[(gösterilecek kod, saklanacak özet)] — kod "abcde-fghij" biçiminde (40 bit), bir kez gösterilir."""
    out = []
    for _ in range(YEDEK_SAYISI):
        ham = secrets.token_hex(5)
        kod = f"{ham[:5]}-{ham[5:]}"
        out.append((kod, _ozet(kod)))
    return out


def yedek_kod_kullan(ozetler, kod):
    """Kod eşleşirse (kalan özetler, True); eşleşmezse (ozetler, False). Tire ve büyük/küçük harf önemsiz."""
    aranan = _ozet(kod)
    for i, ozet in enumerate(ozetler):
        if hmac.compare_digest(ozet, aranan):
            return ozetler[:i] + ozetler[i + 1:], True
    return ozetler, False
