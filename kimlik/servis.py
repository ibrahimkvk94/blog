"""Kimlik okuma satırlarının oluşturulması ve denetimi."""

import datetime

from .models import KimlikKaydi
from .okuma import ALAN_ADLARI, tc_gecerli


def sonuctan_kayit(sonuc, kullanici):
    """okuma.Sonuc → yeni KimlikKaydi (kaydedilmiş)."""
    b = sonuc.bilgiler
    k = KimlikKaydi(ekleyen=kullanici, kaynak="kart")
    for alan in ALAN_ADLARI:
        deger = b.get(alan)
        if deger is None:
            deger = None if alan in ("dogum_tarihi", "son_gecerlilik") else ""
        setattr(k, alan, deger)
    k.tc = (k.tc or "")[:11]
    k.uyarilar = "\n".join(sonuc.uyarilar)
    k.supheli = ",".join(sorted(sonuc.supheli))[:200]
    k.save()
    return k


def denetle(k):
    """Kullanıcı satırı düzelttikten sonra (web ya da Excel): okuma uyarılarını kaldırır, yalnız kalıcı denetimleri
    yazar. Kaydetmez."""
    uyarilar, supheli = [], set()
    if not tc_gecerli(k.tc):
        uyarilar.append("T.C. kimlik no geçersiz (11 hane ve kontrol haneleri tutmalı).")
        supheli.add("tc")
    for alan in ("soyad", "ad"):
        if not getattr(k, alan):
            uyarilar.append(f"{ALAN_ADLARI[alan]} boş.")
            supheli.add(alan)
    if k.son_gecerlilik and k.son_gecerlilik < datetime.date.today():
        uyarilar.append("Kimlik kartının geçerlilik süresi dolmuş.")
        supheli.add("son_gecerlilik")
    k.uyarilar = "\n".join(uyarilar)
    k.supheli = ",".join(sorted(supheli))
    return k
