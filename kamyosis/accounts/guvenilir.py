"""Güvenilir cihazlar (“Bu cihaza güven”): iki adımlı doğrulamayı geçip bu kutuyu işaretleyen tarayıcıya rastgele
bir anahtar çerezi verilir; çerez geçerli kaldıkça (güven kaldırılmadıkça) girişte kod sorulmaz. Parola hâlâ sorulur.
Çerez her girişte yenilenir; veritabanında anahtarın yalnızca özeti durur."""

import hashlib
import re
import secrets

from django.utils import timezone

from .models import GuvenilirCihaz

SURE = 400 * 24 * 60 * 60  # tarayıcıların izin verdiği en uzun çerez ömrü; her girişte baştan başlar


def cerez_adi(user):
    return f"kmy_cihaz_{user.pk}"


def _ozet(anahtar):
    return hashlib.sha256(anahtar.encode()).hexdigest()


def cihaz_adi(request):
    """Tarayıcı ve işletim sistemi, ör. “Chrome · Windows”."""
    ua = request.META.get("HTTP_USER_AGENT", "")
    tarayici = next((ad for desen, ad in ((r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"Firefox/", "Firefox"),
                                         (r"Chrome/", "Chrome"), (r"Safari/", "Safari")) if re.search(desen, ua)),
                    "Tarayıcı")
    sistem = next((ad for desen, ad in ((r"iPhone|iPad", "iPhone / iPad"), (r"Android", "Android"),
                                       (r"Windows", "Windows"), (r"Mac OS X|Macintosh", "Mac"), (r"Linux", "Linux"))
                   if re.search(desen, ua)), "")
    return " · ".join(p for p in (tarayici, sistem) if p)[:120]


def bu_cihaz(request, user):
    """Bu tarayıcı kullanıcı için güvenilir mi: kayıt ya da None."""
    anahtar = request.COOKIES.get(cerez_adi(user))
    if not anahtar or user is None:
        return None
    return GuvenilirCihaz.objects.filter(kullanici=user, ozet=_ozet(anahtar)).first()


def _cerez(request, response, user, anahtar):
    response.set_cookie(cerez_adi(user), anahtar, max_age=SURE, httponly=True, secure=request.is_secure(),
                        samesite="Lax")


def guven(request, response, user):
    """Bu tarayıcıyı güvenilir yapar (iki adımlı doğrulama geçildikten sonra)."""
    anahtar = secrets.token_urlsafe(32)
    GuvenilirCihaz.objects.create(kullanici=user, ozet=_ozet(anahtar), ad=cihaz_adi(request),
                                  son_kullanim=timezone.now())
    _cerez(request, response, user, anahtar)


def kullanildi(request, response, cihaz):
    """Güvenilir cihazla giriş: son kullanım yazılır, çerez ömrü baştan başlar."""
    cihaz.son_kullanim = timezone.now()
    cihaz.save(update_fields=["son_kullanim"])
    _cerez(request, response, cihaz.kullanici, request.COOKIES[cerez_adi(cihaz.kullanici)])


def kaldir(user, pk=None):
    """Güveni kaldırır (pk verilmezse kullanıcının tüm cihazlarından). Dönüş: kaldırılan sayısı."""
    qs = GuvenilirCihaz.objects.filter(kullanici=user)
    if pk is not None:
        qs = qs.filter(pk=pk)
    return qs.delete()[0]
