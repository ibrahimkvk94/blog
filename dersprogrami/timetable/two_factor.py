"""İsteğe bağlı iki adımlı giriş: paroladan sonra telefondaki doğrulama uygulamasının 6 haneli kodu.

Kodlar standart TOTP'dir (RFC 6238: 30 saniyelik adım, HMAC-SHA1, 6 hane); Google / Microsoft Authenticator,
Authy, 1Password gibi uygulamaların hepsi okur. Ek paket gerekmez, karekod segno ile çizilir.

Akış:
- Kullanıcı Hesabım'da açar: gizli anahtar üretilir, karekod gösterilir, uygulamadaki ilk kod doğrulanınca açılır
  ve tek kullanımlık kurtarma kodları bir kez gösterilir. İsterse parolasıyla kapatır.
- Girişte parola doğruysa oturum henüz açılmaz; kullanıcı "bekleyen giriş" olarak doğrulama sayfasına gider.
  Doğru kod (ya da bir kurtarma kodu) gelince oturum açılır. Yanlış kodlar sınırlıdır, bekleyen giriş süreli.
- Telefonu kaybeden kullanıcının doğrulamasını kurum yöneticisi ya da merkez Kullanıcılar sayfasından kaldırır.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time

from django.db import transaction
from django.utils import timezone

from .models import TwoFactor

ISSUER = "Ders Programı"
STEP = 30
DIGITS = 6
WINDOW = 1  # saat kayması için bir önceki / sonraki adım da kabul edilir
RECOVERY_COUNT = 10

# Girişin ikinci adımı (oturumda): parolası doğrulanmış ama kodu henüz girilmemiş kullanıcı.
PENDING = "two_factor_pending"
PENDING_SECONDS = 300
MAX_TRIES = 5


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret):
    return base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)


def code_at(secret, step):
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** DIGITS).zfill(DIGITS)


def current_step(now=None):
    return int((time.time() if now is None else now) // STEP)


def device(user):
    """Kullanıcının açık (doğrulanmış) iki adımlı girişi; yoksa None."""
    if not getattr(user, "pk", None):
        return None
    return TwoFactor.objects.filter(user=user, confirmed_at__isnull=False).first()


def is_enabled(user):
    return device(user) is not None


def _clean(code):
    return "".join(ch for ch in str(code or "") if ch.isalnum()).upper()


def check_code(record, code, now=None):
    """6 haneli kod doğruysa son adımı kaydeder: aynı kod (ya da daha eskisi) ikinci kez geçmez."""
    code = _clean(code)
    if len(code) != DIGITS or not code.isdigit():
        return False
    step = current_step(now)
    for candidate in range(step - WINDOW, step + WINDOW + 1):
        if candidate > record.last_step and hmac.compare_digest(code_at(record.secret, candidate), code):
            # Aynı anda gelen iki istekten yalnızca biri kodu harcayabilsin.
            if TwoFactor.objects.filter(pk=record.pk, last_step__lt=candidate).update(last_step=candidate):
                record.last_step = candidate
                return True
            return False
    return False


def _digest(code):
    return hashlib.sha256(_clean(code).encode()).hexdigest()


def new_recovery_codes(record):
    """Yeni kurtarma kodları (eskileri geçersiz olur). Düz hâlleri yalnızca bir kez gösterilir."""
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}".upper() for _ in range(RECOVERY_COUNT)]
    record.recovery_codes = [_digest(c) for c in codes]
    record.save(update_fields=["recovery_codes"])
    return codes


def use_recovery_code(record, code):
    digest = _digest(code)
    if len(_clean(code)) != 12:
        return False
    with transaction.atomic():
        fresh = TwoFactor.objects.select_for_update().get(pk=record.pk)
        if digest not in fresh.recovery_codes:
            return False
        fresh.recovery_codes = [d for d in fresh.recovery_codes if d != digest]
        fresh.save(update_fields=["recovery_codes"])
    record.recovery_codes = fresh.recovery_codes
    return True


def verify(record, code):
    """Girişte: uygulama kodu ya da kurtarma kodu. Dönüş: "code", "recovery" ya da None."""
    if check_code(record, code):
        return "code"
    if use_recovery_code(record, code):
        return "recovery"
    return None


def start_setup(user):
    """Kurulum: doğrulanmamış yeni anahtar (açık olan doğrulamaya dokunmaz)."""
    record, _ = TwoFactor.objects.get_or_create(user=user, defaults={"secret": new_secret()})
    if record.confirmed_at is None:
        record.secret = new_secret()
        record.last_step = 0
        record.save(update_fields=["secret", "last_step"])
    return record


def setup_record(user):
    return TwoFactor.objects.filter(user=user, confirmed_at__isnull=True).first()


def confirm_setup(record, code):
    """Uygulamadaki ilk kod doğruysa açar ve kurtarma kodlarını döndürür; değilse None."""
    if not check_code(record, code):
        return None
    record.confirmed_at = timezone.now()
    record.save(update_fields=["confirmed_at"])
    return new_recovery_codes(record)


def disable(user):
    TwoFactor.objects.filter(user=user).delete()


def otpauth_uri(record):
    from urllib.parse import quote
    label = quote(f"{ISSUER}:{record.user.get_username()}")
    return f"otpauth://totp/{label}?secret={record.secret}&issuer={quote(ISSUER)}&digits={DIGITS}&period={STEP}"


def qr_svg(record):
    import segno
    return segno.make(otpauth_uri(record), error="m").svg_inline(scale=5, dark="#1c2230", light="#ffffff")


def spaced_secret(record):
    return " ".join(record.secret[i:i + 4] for i in range(0, len(record.secret), 4))
