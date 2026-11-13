"""İş listesi kuralları: kimin kullanabileceği ve durum geçişleri."""

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from .models import Is, IsNotu

IZIN = "is_listesi"


def sahibi_mi(user):
    """Yalnızca izni doğrudan (ya da grubu üzerinden) verilmiş hesap: süper kullanıcılık tek başına yetmez."""
    if not (user.is_authenticated and user.is_active):
        return False
    if not hasattr(user, "_is_listesi_sahibi"):
        user._is_listesi_sahibi = (user.user_permissions.filter(codename=IZIN, content_type__app_label="isler").exists()
                                   or user.groups.filter(permissions__codename=IZIN,
                                                         permissions__content_type__app_label="isler").exists())
    return user._is_listesi_sahibi


def sahip_gerekli(request):
    if not sahibi_mi(request.user):
        raise PermissionDenied("İş listesi yalnızca sistem sahibine açıktır.")


def durum_degistir(is_kaydi, durum, metin="", user=None, claude=False):
    eski = is_kaydi.durum
    is_kaydi.durum = durum
    if durum == Is.TAMAM:
        is_kaydi.tamamlanma = timezone.now()
    if durum != Is.ONAY:
        is_kaydi.onaylandi = is_kaydi.onaylandi and durum == Is.YAPILIYOR
    is_kaydi.save()
    if metin or eski != durum:
        IsNotu.objects.create(is_kaydi=is_kaydi, claude=claude, yazan=None if claude else user, metin=metin or "",
                              durum=durum if eski != durum else "")
    return is_kaydi
