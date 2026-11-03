"""KAMYOSİS: "Ders sınav bilgileri" sayfası — ders kodlarının sınav türü ve zorluğu, kısımların kontenjanı.

Elle düzenlenir ya da Excel'den toplu aktarılır. Excel'de başlık satırı aranır (ilk 15 satır); sütunlar başlıktaki
kelimelerle bulunur, sıra önemli değildir:
- Dersler: "kod" (ders kodu), "tür" (sınav türü), isteğe bağlı "zorluk".
- Kontenjan: "kısım" / "sınıf" / "şube" / "program", "kontenjan" / "öğrenci" / "mevcut".
"İndir" düğmeleri aynı biçimde, mevcut değerlerle dolu bir dosya verir; doldurulup geri yüklenebilir.
"""

from io import BytesIO

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from timetable.models import School, SchoolClass
from timetable.views import _nav

from . import kurallar
from .models import ExamCourse
from .services import course_groups

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _anahtar(metin):
    return "".join(str(metin or "").replace("İ", "i").replace("I", "ı").casefold().split()).replace(".", "")


def _sutunlar(ws, ister):
    """ister: {ad: (başlık parçaları, zorunlu mu)} → (başlık satırı, {ad: sütun}) ya da (None, eksikler)."""
    for r, satir in enumerate(ws.iter_rows(min_row=1, max_row=15, values_only=True), start=1):
        basliklar = [_anahtar(h) for h in satir]
        bulunan = {}
        for ad, (parcalar, _) in ister.items():
            for c, h in enumerate(basliklar):
                if h and any(p in h for p in parcalar) and c not in bulunan.values():
                    bulunan[ad] = c
                    break
        if all(ad in bulunan for ad, (_, zorunlu) in ister.items() if zorunlu):
            return r, bulunan
    return None, [ad for ad, (_, zorunlu) in ister.items() if zorunlu]


def _kitap(dosya):
    from openpyxl import load_workbook

    return load_workbook(dosya, read_only=True, data_only=True)


def dersleri_aktar(school, dosya):
    """Dönüş: (güncellenen, bulunamayan kodlar, hata iletisi)."""
    try:
        ws = _kitap(dosya).active
    except Exception:
        return 0, [], "Dosya okunamadı; .xlsx biçiminde Excel dosyası seçin."
    baslik, sutun = _sutunlar(ws, {"kod": (["kod"], True), "tur": (["tür", "tur"], True), "zorluk": (["zorluk"], False)})
    if baslik is None:
        return 0, [], "Başlık satırında “Ders kodu” ve “Sınav türü” sütunları bulunamadı."
    kodlar = {code for code, *_ in course_groups(school)}
    guncellenen, bilinmeyen = 0, []
    for satir in ws.iter_rows(min_row=baslik + 1, values_only=True):
        kod = str(satir[sutun["kod"]] or "").strip()
        if not kod:
            continue
        tur = kurallar.tur_normalize(str(satir[sutun["tur"]] or ""))
        degerler = {"exam_type": tur}
        if "zorluk" in sutun and satir[sutun["zorluk"]] not in (None, ""):
            degerler["difficulty"] = kurallar.zorluk(satir[sutun["zorluk"]])
        ExamCourse.objects.update_or_create(institution_id=school.institution_id, code=kod, defaults=degerler)
        guncellenen += 1
        if kod not in kodlar:
            bilinmeyen.append(kod)
    return guncellenen, bilinmeyen, None


def kontenjanlari_aktar(school, dosya):
    """Dönüş: (güncellenen, bulunamayan kısımlar, hata iletisi)."""
    try:
        ws = _kitap(dosya).active
    except Exception:
        return 0, [], "Dosya okunamadı; .xlsx biçiminde Excel dosyası seçin."
    baslik, sutun = _sutunlar(ws, {"kisim": (["kısım", "kisim", "sınıf", "sinif", "şube", "sube", "program"], True),
                                   "kontenjan": (["kontenjan", "öğrenci", "ogrenci", "mevcut"], True)})
    if baslik is None:
        return 0, [], "Başlık satırında kısım ve kontenjan sütunları bulunamadı."
    siniflar = {}
    for c in SchoolClass.objects.filter(school=school):
        for ad in (c.short, c.name):
            if ad:
                siniflar.setdefault(_anahtar(ad), c)
    guncellenen, bulunamayan = 0, []
    for satir in ws.iter_rows(min_row=baslik + 1, values_only=True):
        ad, deger = satir[sutun["kisim"]], satir[sutun["kontenjan"]]
        if ad in (None, ""):
            continue
        try:
            sayi = int(float(deger))
        except (TypeError, ValueError):
            continue
        sinif = siniflar.get(_anahtar(ad))
        if sinif is None:
            bulunamayan.append(str(ad))
            continue
        if sinif.student_count != sayi:
            sinif.student_count = max(0, sayi)
            sinif.save(update_fields=["student_count"])
        guncellenen += 1
    return guncellenen, bulunamayan, None


def _excel(baslik, satirlar, ad):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.append(baslik)
    for c in ws[1]:
        c.font = Font(bold=True)
    for s in satirlar:
        ws.append(s)
    for i, genislik in enumerate((14, 48, 22, 10)[: len(baslik)], start=1):
        ws.column_dimensions[chr(64 + i)].width = genislik
    cikti = BytesIO()
    wb.save(cikti)
    r = HttpResponse(cikti.getvalue(), content_type=XLSX)
    r["Content-Disposition"] = f'attachment; filename="{ad}.xlsx"'
    return r


class _Dosya(forms.Form):
    dosya = forms.FileField()


def courses(request, pk):
    school = get_object_or_404(School, pk=pk)
    back = reverse("sinav:courses", args=[school.pk])
    info = kurallar.bilgiler(school.institution_id)
    groups = course_groups(school)
    classes = list(SchoolClass.objects.filter(school=school).order_by("name"))

    if request.GET.get("indir") == "dersler":
        return _excel(["Ders kodu", "Ders adı", "Sınav türü", "Zorluk"],
                      [[code, name, info[code].exam_type if code in info else "",
                        info[code].difficulty if code in info else kurallar.VARSAYILAN_ZORLUK] for code, name, *_ in groups],
                      f"ders_sinav_bilgileri_{school.pk}")
    if request.GET.get("indir") == "kontenjan":
        return _excel(["Kısım", "Kısım adı", "Kontenjan"], [[c.short or c.name, c.name, c.student_count or 0] for c in classes],
                      f"kontenjanlar_{school.pk}")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_courses":
            n = 0
            for code in request.POST.getlist("code"):
                tur = kurallar.tur_normalize(request.POST.get(f"tur-{code}", ""))
                z = kurallar.zorluk(request.POST.get(f"zorluk-{code}"))
                old = info.get(code)
                if old is None and not tur and z == kurallar.VARSAYILAN_ZORLUK:
                    continue  # boş satır: kayıt açma
                if old is None or (old.exam_type, old.difficulty) != (tur, z):
                    ExamCourse.objects.update_or_create(institution_id=school.institution_id, code=code,
                                                        defaults={"exam_type": tur, "difficulty": z})
                    n += 1
            messages.success(request, f"{n} dersin sınav bilgisi güncellendi." if n else "Değişiklik yok.")
            return redirect(back)
        if action == "save_quotas":
            n = 0
            for c in classes:
                raw = request.POST.get(f"kontenjan-{c.pk}")
                try:
                    sayi = max(0, int(raw))
                except (TypeError, ValueError):
                    continue
                if (c.student_count or 0) != sayi:
                    c.student_count = sayi
                    c.save(update_fields=["student_count"])
                    n += 1
            messages.success(request, f"{n} kısmın kontenjanı güncellendi." if n else "Değişiklik yok.")
            return redirect(back + "#kontenjan")
        if action in ("import_courses", "import_quotas"):
            form = _Dosya(request.POST, request.FILES)
            if not form.is_valid():
                messages.error(request, "Excel dosyası seçin.")
                return redirect(back)
            if action == "import_courses":
                n, eksik, hata = dersleri_aktar(school, form.cleaned_data["dosya"])
                ad = "ders"
            else:
                n, eksik, hata = kontenjanlari_aktar(school, form.cleaned_data["dosya"])
                ad = "kısım"
            if hata:
                messages.error(request, hata)
            else:
                messages.success(request, f"{n} {ad} aktarıldı.")
                if eksik:
                    liste = ", ".join(eksik[:12]) + (" …" if len(eksik) > 12 else "")
                    messages.warning(request, f"Bu programda bulunamayan {len(eksik)} {ad}: {liste}"
                                     + (" (bilgileri yine de kaydedildi)." if ad == "ders" else "."))
            return redirect(back + ("#kontenjan" if action == "import_quotas" else ""))

    rows = []
    for code, name, _subject, lessons in groups:
        c = info.get(code)
        tur = c.exam_type if c else ""
        rows.append({"code": code, "name": name, "tur": tur, "zorluk": c.difficulty if c else kurallar.VARSAYILAN_ZORLUK,
                     "kayitli": c is not None, "uyg": kurallar.plana_alinmaz(tur), "aile": kurallar.tur_ailesi(tur),
                     "yil": kurallar.sinif_yili(code),
                     "kisimlar": sorted({cl.short or cl.name for lesson in lessons for cl in lesson.classes.all()})})
    return render(request, "sinav/courses.html", _nav(
        school, "sinav-bilgileri", rows=rows, classes=classes, turler=kurallar.SIK_TURLER, zorluklar=kurallar.ZORLUKLAR,
        eksik_tur=sum(1 for r in rows if not r["tur"]), uyg=sum(1 for r in rows if r["uyg"]),
        bos_kontenjan=sum(1 for c in classes if not c.student_count),
    ))
