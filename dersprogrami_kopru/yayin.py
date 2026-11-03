"""Modülde yayınlanan programı KAMYOSİS'e (program uygulaması) taslak sürüm olarak aktarır.

Yol: modülün aSc XML dışa aktarımı → kimlikler kalıcı iş anahtarlarına çevrilir → program.asc.ice_aktar.
KAMYOSİS'teki asıl yayın (başlangıç tarihiyle) Ders Planları ekranından elle yapılır.
"""

import hashlib
import io
import xml.etree.ElementTree as ET

from django.db import transaction
from django.db.models import ProtectedError

from personel.models import Personel
from program import eslestirme
from program.asc import ad_anahtari, ice_aktar
from program.models import ProgramOgretmeni, ProgramSurumu
from timetable.asc_xml import export_school


class AktarimHatasi(Exception):
    pass


def kaynak_adi(timetable):
    return f"dersprogrami:{timetable.pk}"


def _kimlik(tur, deger):
    """KAMYOSİS'te asc_id en çok 40 karakter: uzun adlar özetlenir."""
    kimlik = f"DP-{tur}:{deger}"
    if len(kimlik) > 40:
        kimlik = f"DP-{tur}#" + hashlib.sha1(deger.encode("utf-8")).hexdigest()[:24]
    return kimlik


def _ids(deger):
    return [x for x in (deger or "").split(",") if x]


def hafta_donem_denetle(kok):
    """KAMYOSİS her hafta aynı programı bekler: A/B haftalı ya da dönemli dersler aktarılamaz."""
    farkli = [d for d in kok.iter("lesson")
              if d.get("weeksdefid", "WALL") != "WALL" or d.get("termsdefid", "PALL") != "PALL"]
    if farkli:
        raise AktarimHatasi(f"{len(farkli)} ders yalnızca belirli haftalarda ya da dönemlerde yapılıyor (A/B haftası). "
                            "KAMYOSİS ders takibi bunu henüz desteklemiyor.")


def kimlikleri_kalicilastir(kok, ogretmen_tc):
    """Veritabanı numarasından üretilen kimlikleri (S12, C3…) koda/ada dayalı kimliklere çevirir.

    Böylece program kopyalansa da KAMYOSİS'teki ders, kısım, derslik ve öğretmen kayıtları aynı kalır.
    `ogretmen_tc`: {"T<pk>": tc} → dönüş: {yeni öğretmen kimliği: tc}. TC kimliğe yazılmaz, yalnızca bellekte eşleme için.
    """
    harita = {}

    for el in kok.iter("subject"):
        harita[el.get("id")] = _kimlik("D", (el.get("short") or el.get("name") or "").strip())
    for el in kok.iter("classroom"):
        harita[el.get("id")] = _kimlik("R", (el.get("name") or el.get("short") or "").strip())
    sinif_kodu = {}
    for el in kok.iter("class"):
        kod = (el.get("short") or el.get("name") or "").strip()
        sinif_kodu[el.get("id")] = kod
        harita[el.get("id")] = _kimlik("K", kod)
    for el in kok.iter("group"):
        kod = sinif_kodu.get(el.get("classid"), "")
        if el.get("entireclass") == "1":
            harita[el.get("id")] = _kimlik("G", f"{kod}/0")
        else:
            harita[el.get("id")] = _kimlik("G", f"{kod}/{el.get('divisiontag')}/{(el.get('name') or '').strip()}")
    ogretmenler = list(kok.iter("teacher"))
    anahtarlar = [ad_anahtari(el.get("name")) for el in ogretmenler]
    for el, anahtar in zip(ogretmenler, anahtarlar):
        # Aynı adlı iki öğretmen birleşmesin: ayırt etmek için modüldeki numara eklenir
        harita[el.get("id")] = _kimlik("O", anahtar if anahtarlar.count(anahtar) == 1 else f"{anahtar}~{el.get('id')}")

    def cevir(el, *alanlar):
        for alan in alanlar:
            if el.get(alan):
                el.set(alan, ",".join(harita.get(x, x) for x in _ids(el.get(alan))))

    for etiket in ("subject", "classroom", "class", "group", "teacher"):
        for el in kok.iter(etiket):
            cevir(el, "id")
    for el in kok.iter("class"):
        cevir(el, "classroomids", "teacherid")
    for el in kok.iter("group"):
        cevir(el, "classid")
    for el in kok.iter("lesson"):
        cevir(el, "classids", "groupids", "subjectid", "teacherids", "classroomids")
    for el in kok.iter("card"):
        cevir(el, "classroomids")
    return {harita[eski]: tc for eski, tc in ogretmen_tc.items() if eski in harita and tc}


def kamyosise_gonder(timetable, kullanici):
    """Programı KAMYOSİS'e taslak sürüm olarak aktarır: (sürüm, rapor). Aynı programın önceki taslağı değiştirilir."""
    school = timetable.school
    kok = ET.fromstring(export_school(school, timetable))
    hafta_donem_denetle(kok)
    tc = kimlikleri_kalicilastir(kok, {f"T{pk}": no for pk, no in school.teachers.values_list("pk", "tc_no")})
    veri = io.BytesIO(ET.tostring(kok, encoding="utf-8", xml_declaration=True))

    with transaction.atomic():
        for eski in ProgramSurumu.objects.filter(kaynak_dosya=kaynak_adi(timetable), durum=ProgramSurumu.TASLAK):
            try:
                with transaction.atomic():
                    eski.delete()
            except ProtectedError:
                pass
        surum, rapor = ice_aktar(veri, surum_adi=f"{school.name} · {timetable.name}"[:120],
                                 kaynak_dosya=kaynak_adi(timetable), kullanici=kullanici)
        surum.aciklama = "Ders Programı modülünde yayınlandığında otomatik aktarıldı."
        surum.save(update_fields=["aciklama"])

        # Adı tutmayan öğretmenler personele TC kimlik numarasından bağlanır
        bekleyen = ProgramOgretmeni.objects.filter(asc_id__in=tc, durum=ProgramOgretmeni.BEKLIYOR, personel=None)
        tc_ile = 0
        for o in bekleyen:
            p = Personel.objects.filter(personel_kodu=tc[o.asc_id]).first()
            if p is not None:
                eslestirme.eslestir(o, p)
                tc_ile += 1
        if tc_ile:
            rapor.sayilar["TC ile eşleşen öğretmen"] = tc_ile
            rapor.sayilar["Eşleştirme bekleyen öğretmen"] = max(0, rapor.sayilar.get("Eşleştirme bekleyen öğretmen", 0) - tc_ile)
    return surum, rapor
