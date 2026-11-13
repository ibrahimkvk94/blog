"""Kullanıcılar ve yetkiler (yalnız sistem yöneticileri): hesap türleri, hesap × modül yetki tablosu, hesap işlemleri.

Yetki seviyeleri: 0 yok, 1 görür, 2 düzenler, 3 yönetir. Kapsam: "bolum" = kendi birimi (bölüm hesabında bölümü, şube /
kısım hesabında birimi ve alt birimleri), "tum" = tüm okul. Bir birime verilen yetki alt birimlerine de geçer
(core/yetki.py); tablo kullanımdaki modüllerin doğrudan yetkilerini düzenler, üst birimden gelenleri kilitli gösterir.
Her değişiklik Yönetim Paneli günlüğüne (LogEntry) yazılır; sayfalardaki "son değişiklikler" oradan gelir.
"""

import secrets
from datetime import timedelta

from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from .bolum_yetkileri import moduller
from .models import Yetki

SEVIYE_ADLARI = {0: "Yok", 1: "Görür", 2: "Düzenler", 3: "Yönetir"}
KAPSAM_ADLARI = {Yetki.BOLUM: "kendi birimi", Yetki.TUM: "tüm okul"}

# (kod, etiket, ikon, renk)
TURLER = [
    ("yonetici", "Sistem yöneticisi", "shield-lock", "#b8860b"),
    ("tum", "Tüm okul yetkilisi", "globe2", "#7c3aed"),
    ("bolum", "Bölüm hesabı", "mortarboard", "#2f5d8a"),
    ("birim", "Şube / kısım hesabı", "diagram-3", "#0f766e"),
    ("kisisel", "Kişisel / diğer", "person", "#64748b"),
]
TUR = {t[0]: {"kod": t[0], "ad": t[1], "ikon": t[2], "renk": t[3]} for t in TURLER}


def hesap_turu(u):
    if u.is_superuser:
        return "yonetici"
    tum = any(y.kapsam == Yetki.TUM for y in u.yetkiler.all())
    if tum:
        return "tum"
    if u.teskilat_birimi_id:
        return "birim"
    if u.bolum_id:
        return "bolum"
    return "kisisel"


def varsayilan_kapsam(u):
    """Yeni verilen yetkinin kapsamı: bölüme / birime bağlı hesapta kendi birimi, diğerlerinde tüm okul."""
    return Yetki.BOLUM if (u.bolum_id or u.teskilat_birimi_id) and not u.is_superuser else Yetki.TUM


def gorunen_ad(u):
    ad = u.get_full_name()
    if ad or u.is_superuser:
        return ad or u.username
    if u.teskilat_birimi_id:
        return u.teskilat_birimi.ad
    if u.bolum_id:
        return u.bolum.ad
    return u.username


def bas_harfler(metin):
    kelimeler = [k for k in metin.replace("/", " ").split() if k[:1].isalpha() and k.lower() not in {"ve", "ile"}]
    return ("".join(k[0] for k in kelimeler[:2]) or metin[:2]).upper()


def bagli_yer(u):
    """Hesabın bağlı olduğu yer (alt satır metni)."""
    if u.teskilat_birimi_id:
        return u.teskilat_birimi.ad
    if u.bolum_id:
        return f"{u.bolum.kod} · {u.bolum.ad}" if u.bolum.kod else u.bolum.ad
    if u.personel_id:
        return u.personel.tam_ad
    return ""


def kullanicilar():
    User = get_user_model()
    return list(
        User.objects.select_related("bolum", "teskilat_birimi", "personel__rutbe", "personel__sinif",
                                    "personel__unvan", "iki_adim")
        .prefetch_related("yetkiler").annotate(cihaz_sayisi=Count("guvenilir_cihazlar"))
        .order_by("-is_superuser", "username"))


def modul_gruplari(mods):
    gruplar = []
    for m in mods:
        if gruplar and gruplar[-1]["grup"] == m.grup:
            gruplar[-1]["sayi"] += 1
        else:
            gruplar.append({"grup": m.grup, "sayi": 1})
    return gruplar


def hucre(u, m, dogrudan=None):
    """Kullanıcının modüldeki etkin durumu: {"seviye", "kapsam", "miras", "kilit"}. miras: seviyeyi üst birimdeki
    yetki belirliyorsa o yetki (değiştirilince modül yetkilerine çevrilir, bkz. tablo_kaydet)."""
    if u.is_superuser:
        return {"seviye": 3, "kapsam": Yetki.TUM, "miras": None, "kilit": "Sistem yöneticisi: her yerde tam yetki"}
    if dogrudan is None:
        dogrudan = {y.birim_id: y for y in u.yetkiler.all()}
    y = dogrudan.get(m.id)
    ust = [dogrudan[b] for b in m.ataler[:-1] if b in dogrudan]
    miras = max(ust, key=lambda x: x.seviye) if ust else None
    if miras and (y is None or miras.seviye > y.seviye):
        return {"seviye": miras.seviye, "kapsam": miras.kapsam, "miras": miras, "kilit": ""}
    return {"seviye": y.seviye if y else 0, "kapsam": y.kapsam if y else varsayilan_kapsam(u), "miras": None,
            "kilit": ""}


def mirasi_ac(yapan, u, ust, mods):
    """Üst birimdeki yetkiyi (ör. Plan Program Kısmı) altındaki kullanımdaki modüllerin yetkilerine çevirir; böylece
    modüller tek tek değiştirilebilir. Dönüş: günlük metni."""
    var = set(u.yetkiler.values_list("birim_id", flat=True))
    acilan = []
    for m in mods.values():
        if ust.birim_id in m.ataler[:-1] and m.id not in var:
            Yetki.objects.create(kullanici=u, birim=m, seviye=ust.seviye, kapsam=ust.kapsam)
            acilan.append(m.ad)
    ad = ust.birim.ad
    ust.delete()
    return f"{ad} yetkisi modüllere çevrildi ({', '.join(acilan) or 'modül yok'})"


def isle(u, simdi=None):
    """Kullanıcıya liste / sayfa için gereken alanları ekler."""
    simdi = simdi or timezone.now()
    from accounts.guvenlik import kilit_kalan_dk

    u.tur = TUR[hesap_turu(u)]
    u.gorunen = gorunen_ad(u)
    u.harfler = bas_harfler(u.gorunen)
    u.yer = bagli_yer(u)
    u.yer_alt = "" if u.gorunen in u.yer else u.yer  # alt satırda adı tekrarlamasın
    ia = getattr(u, "iki_adim", None) if hasattr(u, "iki_adim") else None
    u.iki_adim_acik = bool(ia and ia.etkin)
    u.kilit_dk = kilit_kalan_dk(u.username)
    u.son_hafta = bool(u.last_login and u.last_login >= simdi - timedelta(days=7))
    return u


def tablo():
    mods = moduller()
    simdi = timezone.now()
    satirlar = []
    for u in kullanicilar():
        isle(u, simdi)
        dogrudan = {y.birim_id: y for y in u.yetkiler.all()}
        u.hucreler = [{"modul": m, **hucre(u, m, dogrudan)} for m in mods]
        u.yetki_sayisi = sum(1 for h in u.hucreler if h["seviye"] or h["miras"])
        satirlar.append(u)
    return mods, satirlar


def ozet(satirlar):
    aktif = [u for u in satirlar if u.is_active]
    return {"toplam": len(satirlar), "aktif": len(aktif), "pasif": len(satirlar) - len(aktif),
            "iki_adim": sum(u.iki_adim_acik for u in aktif), "son_hafta": sum(u.son_hafta for u in aktif),
            "kilitli": sum(1 for u in satirlar if u.kilit_dk),
            "turler": [{**TUR[k], "sayi": sum(1 for u in satirlar if u.tur["kod"] == k)} for k, *_ in TURLER]}


# ------------------------------------------------------------------ yazma

def gunluge_yaz(yapan, hedef, metin, ekleme=False):
    LogEntry.objects.create(
        user_id=yapan.pk, content_type=ContentType.objects.get_for_model(hedef), object_id=str(hedef.pk),
        object_repr=str(hedef.username)[:200], action_flag=ADDITION if ekleme else CHANGE,
        change_message=f"[Kullanıcılar] {metin}"[:2000])


def gecmis(hedef=None, adet=15):
    qs = LogEntry.objects.filter(content_type=ContentType.objects.get_for_model(get_user_model()))
    if hedef is not None:
        qs = qs.filter(object_id=str(hedef.pk))
    kayitlar = list(qs.select_related("user").order_by("-action_time")[:adet])
    for e in kayitlar:  # Yönetim Paneli kayıtları JSON; buradakiler düz metin
        metin = e.get_change_message() or ("Hesap açıldı" if e.is_addition() else "Değiştirildi")
        e.metin = metin.removeprefix("[Kullanıcılar] ")
        e.panelden = not e.change_message.startswith("[Kullanıcılar]")
    return kayitlar


def yetki_yaz(u, birim, seviye, kapsam):
    """Doğrudan yetkiyi istenen duruma getirir; değişiklik metni ya da None döner. Sinyaller (Ders Programı modül
    üyeliği) çalışsın diye kayıtlar tek tek yazılır / silinir."""
    if seviye not in SEVIYE_ADLARI or kapsam not in KAPSAM_ADLARI:
        return None
    y = Yetki.objects.filter(kullanici=u, birim=birim).first()
    eski = f"{SEVIYE_ADLARI[y.seviye]} ({KAPSAM_ADLARI.get(y.kapsam, y.kapsam)})" if y else "Yok"
    if seviye == 0:
        if y is None:
            return None
        y.delete()
        return f"{birim.ad}: {eski} → Yok"
    if y is None:
        Yetki.objects.create(kullanici=u, birim=birim, seviye=seviye, kapsam=kapsam)
    elif (y.seviye, y.kapsam) == (seviye, kapsam):
        return None
    else:
        y.seviye, y.kapsam = seviye, kapsam
        y.save(update_fields=["seviye", "kapsam"])
    return f"{birim.ad}: {eski} → {SEVIYE_ADLARI[seviye]} ({KAPSAM_ADLARI[kapsam]})"


@transaction.atomic
def tablo_kaydet(yapan, degerler):
    """degerler: ["kullanıcı:modül:seviye:kapsam", ...] (yalnız değişen hücreler). Dönüş: değişen yetki sayısı."""
    User = get_user_model()
    mods = {m.id: m for m in moduller()}
    istek = {}
    for d in degerler:
        p = d.split(":")
        if len(p) == 4 and p[0].isdigit() and p[1].isdigit() and p[2].isdigit() and int(p[1]) in mods:
            istek.setdefault(int(p[0]), []).append((mods[int(p[1])], int(p[2]), p[3]))
    n = 0
    for u in User.objects.filter(pk__in=istek, is_superuser=False):
        notlar = []
        for m, seviye, kapsam in istek[u.pk]:
            while True:  # üst birimden gelen yetki önce modül yetkilerine çevrilir
                miras = hucre(u, m, {y.birim_id: y for y in Yetki.objects.filter(kullanici=u).select_related("birim")})["miras"]
                if miras is None:
                    break
                notlar.append(mirasi_ac(yapan, u, miras, mods))
            metin = yetki_yaz(u, m, seviye, kapsam)
            if metin:
                notlar.append(metin)
        if notlar:
            gunluge_yaz(yapan, u, "Yetki: " + "; ".join(notlar))
            n += len(notlar)
    return n


def oturumlari_kapat(u):
    n = 0
    for s in Session.objects.filter(expire_date__gt=timezone.now()):
        try:
            sahip = s.get_decoded().get("_auth_user_id")
        except Exception:
            continue
        if sahip == str(u.pk):
            s.delete()
            n += 1
    return n


def parola_uret():
    """Okunaklı rastgele parola (karışan harfler yok): ör. "Kmr7-Tnz4-Pa"."""
    harf, buyuk, rakam = "abcdefghjkmnpqrstuvwxyz", "ABCDEFGHJKLMNPQRSTUVWXYZ", "23456789"
    parca = lambda: secrets.choice(buyuk) + "".join(secrets.choice(harf) for _ in range(2)) + secrets.choice(rakam)
    return f"{parca()}-{parca()}-{secrets.choice(buyuk)}{secrets.choice(harf)}"


def _dogrudan(u):
    return {y.birim_id: y for y in Yetki.objects.filter(kullanici=u).select_related("birim")}


def diger_yetkiler(u):
    """Tablo sütunlarında olmayan birimlerdeki yetkiler (ör. Plan Program Kısmı başlığı, hazırlanan modüller)."""
    mod_idler = {m.id for m in moduller()}
    return [y for y in Yetki.objects.filter(kullanici=u).select_related("birim").order_by("birim__sira")
            if y.birim_id not in mod_idler]


@transaction.atomic
def hesap_yetkileri_kaydet(yapan, u, istek, kaldirilacak=()):
    """Hesap sayfasındaki yetki formu. istek: {modül id: (seviye, kapsam)}; kaldirilacak: diğer yetkilerin kimlikleri.
    Dönüş: değişiklik sayısı."""
    mods = {m.id: m for m in moduller()}
    notlar = []
    for y in Yetki.objects.filter(kullanici=u, pk__in=list(kaldirilacak)).select_related("birim"):
        notlar.append(f"{y.birim.ad}: {SEVIYE_ADLARI.get(y.seviye, y.seviye)} → Yok")
        y.delete()
    for mid, (seviye, kapsam) in istek.items():
        m = mods.get(mid)
        if m is None:
            continue
        h = hucre(u, m, _dogrudan(u))
        if (h["seviye"], h["kapsam"] if h["seviye"] else kapsam) == (seviye, kapsam):
            continue
        while h["miras"] is not None:
            notlar.append(mirasi_ac(yapan, u, h["miras"], mods))
            h = hucre(u, m, _dogrudan(u))
        metin = yetki_yaz(u, m, seviye, kapsam)
        if metin:
            notlar.append(metin)
    if notlar:
        gunluge_yaz(yapan, u, "Yetki: " + "; ".join(notlar))
    return len(notlar)


@transaction.atomic
def yetkileri_kopyala(kaynak, hedef):
    """Kaynak hesabın tüm yetkilerini (seviye ve kapsamıyla) hedefe yazar. Dönüş: kopyalanan sayı."""
    n = 0
    for y in kaynak.yetkiler.select_related("birim"):
        if yetki_yaz(hedef, y.birim, y.seviye, y.kapsam):
            n += 1
    return n
