from django import template

register = template.Library()


@register.filter
def bas_harfler(ad):
    """"Ali Can KAYA" → "AK" (ilk ve son sözcüğün baş harfi)."""
    parcalar = str(ad or "").split()
    if not parcalar:
        return "?"
    return (parcalar[0][:1] + (parcalar[-1][:1] if len(parcalar) > 1 else "")).upper()


@register.simple_tag
def isaretler(p):
    """Rütbe / sınıf / akademik unvan işaretleri: [(svg, etiket)]."""
    from yoklama.isaretler import personel_isaretleri

    return personel_isaretleri(p)


@register.filter
def girinti(derinlik):
    """Seçim kutusunda alt birim girintisi."""
    from django.utils.safestring import mark_safe

    return mark_safe("&nbsp;&nbsp;&nbsp;" * int(derinlik or 0) + ("└ " if derinlik else ""))


SIK_VARSAYILAN = ["Yıllık İzin", "Günlük İzin", "Hastane", "İstirahat", "Yurtiçi Görev", "Kurs"]


@register.simple_tag
def tur_secici(turler, secili=None, adet=6):
    """Kayıt formundaki tür seçimi: {"gruplar": [(ad, [tür])], "sik": [tür]}. Sık kullanılanlar son bir yılda en çok
    girilen türler; az kayıt varsa varsayılan listeyle tamamlanır."""
    import datetime

    from django.db.models import Count
    from django.utils import timezone

    from yoklama.models import GRUPLAR, YoklamaKaydi

    turler = list(turler)
    by_pk = {t.pk: t for t in turler}
    gruplar = [(ad, [t for t in turler if t.grup == kod]) for kod, ad in GRUPLAR]
    sinir = timezone.now() - datetime.timedelta(days=365)
    sayilar = (YoklamaKaydi.objects.filter(olusturma__gte=sinir, tur_id__in=by_pk).values("tur_id")
               .annotate(n=Count("pk")).order_by("-n"))
    sik = [by_pk[s["tur_id"]] for s in sayilar[:adet]]
    for ad in SIK_VARSAYILAN:
        if len(sik) >= adet:
            break
        t = next((x for x in turler if x.ad == ad), None)
        if t and t not in sik:
            sik.append(t)
    return {"gruplar": [g for g in gruplar if g[1]], "sik": sik}


@register.filter
def sure_bicimi(k):
    """Düzenlenen kaydın formdaki süre biçimi: tam / oo (öğleden önce) / os (öğleden sonra) / saat."""
    from yoklama.models import OGLEDEN_ONCE, OGLEDEN_SONRA

    if not k or k.tam_gun:
        return "tam"
    aralik = (k.yerel_bas.time(), k.yerel_bit.time())
    if k.tur.yarim_gun and aralik == OGLEDEN_ONCE:
        return "oo"
    if k.tur.yarim_gun and aralik == OGLEDEN_SONRA:
        return "os"
    return "saat"
