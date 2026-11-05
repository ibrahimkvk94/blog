"""KAMYOSİS personeli ↔ Ders Programı öğretmeni eşleştirmesi ve künye (rütbe, sınıf, unvan) eşitlemesi.

Öğretmen ad soyadla eşleştirilir: önce aSc adı → KAMYOSİS program öğretmeni → personel, sonra personel
ad soyadı. T.C. kimlik no kullanılmaz. Künye kaynağı KAMYOSİS'tir: modülde öğretmenin "ünvan / rütbe"
alanı elle değiştirilse de bir sonraki eşitlemede KAMYOSİS'teki değer yazılır.
"""

from personel.models import Personel


def _ad(metin):
    return " ".join((metin or "").replace("İ", "i").replace("I", "ı").lower().split())


def ogretmen_eslesmesi(okul):
    """{personel_id: Teacher}. Aynı personele iki öğretmen düşerse (ya da ad birden çok personele uyarsa) eşleşmez."""
    from program.models import ProgramOgretmeni
    from timetable.models import Teacher

    aSc = {}
    for po in ProgramOgretmeni.objects.exclude(personel=None):
        aSc.setdefault(_ad(po.ad), set()).add(po.personel_id)
    ad_soyad = {}
    for pk, ad in Personel.objects.filter(aktif=True).values_list("pk", "ad_soyad"):
        ad_soyad.setdefault(_ad(ad), set()).add(pk)
    sonuc, cift = {}, set()
    for t in Teacher.objects.filter(school=okul):
        ad = _ad(f"{t.first_name} {t.last_name}")
        adaylar = aSc.get(ad) or ad_soyad.get(ad) or set()
        if len(adaylar) != 1:
            continue
        pk = next(iter(adaylar))
        if pk in sonuc:
            cift.add(pk)
        sonuc[pk] = t
    for pk in cift:
        del sonuc[pk]
    return sonuc


def kunyeleri_esitle(okullar=None, personel_idler=None):
    """Eşleşen öğretmenlerin "ünvan / rütbe" alanını KAMYOSİS künyesiyle, "bölüm" alanını personelin bölüm koduyla,
    "branş" alanını (KAMYOSİS'te doluysa) personelin branşıyla günceller (Sınav Planlama'da bölüme göre süzmek için). Dönüş: değişen öğretmen sayısı."""
    from timetable.models import School, Teacher

    personeller = {p.pk: p for p in Personel.objects.select_related("unvan", "rutbe", "sinif", "bolum")}
    degisen = 0
    for okul in (okullar if okullar is not None else School.objects.all()):
        for pk, t in ogretmen_eslesmesi(okul).items():
            if personel_idler is not None and pk not in personel_idler:
                continue
            p = personeller[pk]
            kunye, bolum = p.kunye[:100], (p.bolum.kod if p.bolum else "")[:60]
            brans = (p.brans or t.branch)[:100]  # KAMYOSİS'te boşsa modülde girilen branş silinmez
            if (t.title, t.department, t.branch) != (kunye, bolum, brans):
                # update(): öğretmen kayıt sinyali yeniden tetiklenmesin
                Teacher.objects.filter(pk=t.pk).update(title=kunye, department=bolum, branch=brans)
                degisen += 1
    return degisen
