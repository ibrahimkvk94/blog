"""KAMYOSİS: "Ders sınav bilgileri" sayfası — ders kodlarının sınav türü ve zorluğu, kısımların kontenjanı.

Elle düzenlenir ya da Excel'den toplu aktarılır. Excel'de başlık satırı aranır (ilk 15 satır); sütunlar başlıktaki
kelimelerle bulunur, sıra önemli değildir:
- Dersler: "kod" (ders kodu), "tür" (sınav türü), isteğe bağlı "zorluk".
- Kontenjan: "program", "sınıf" (düzey: 1 / 2), "kontenjan" / "öğrenci" / "mevcut"; programı olmayan kısım için
  "kısım" sütunu (kısa ad ya da ad).
"İndir" düğmeleri aynı biçimde, mevcut değerlerle dolu bir dosya verir; doldurulup geri yüklenebilir.

Kontenjan program × sınıf düzeyine girilir (ör. SVN 1. sınıf: 120) ve programın kısımlarına eşit bölünür; kısımların
programı ve düzeyi bir kez kısa adlarından atanır ("10MKT" → MKT, 1. sınıf; bkz. kurallar.kisim_bilgisi).
Kontenjan değişince dönemlerdeki sınavların (elle girilmemiş) öğrenci sayıları yeniden hesaplanır.
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


def program_gruplari(classes):
    """([{"program", "sinif", "kisimlar", "toplam"}], programı olmayan kısımlar)."""
    gruplar, programsiz = {}, []
    for c in classes:
        if c.program:
            gruplar.setdefault((c.program, c.grade), []).append(c)
        else:
            programsiz.append(c)
    satirlar = []
    for (program, sinif), kisimlar in sorted(gruplar.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
        kisimlar.sort(key=lambda c: c.sort_key)
        satirlar.append({"program": program, "sinif": sinif, "kisimlar": kisimlar,
                         "toplam": sum(c.student_count or 0 for c in kisimlar), "anahtar": f"{program}|{sinif or 0}"})
    return satirlar, programsiz


def programlari_ata(classes):
    """Programı boş kısımlara kısa adlarından program (ve boşsa sınıf düzeyi) atar. Dönüş: atanan kısım sayısı."""
    n = 0
    for c in classes:
        if c.program:
            continue
        program, sinif = kurallar.kisim_bilgisi(c.short or c.name)
        if not program:
            continue
        c.program = program[:30]
        alanlar = ["program"]
        if c.grade is None and sinif is not None:
            c.grade = sinif
            alanlar.append("grade")
        c.save(update_fields=alanlar)
        n += 1
    return n


def program_kontenjani_yaz(grup, toplam):
    """Grubun (program × sınıf) kontenjanını kısımlara böler. Dönüş: değişti mi."""
    if toplam == grup["toplam"]:
        return False
    dagilim = kurallar.kontenjan_dagit(toplam, grup["kisimlar"])
    for c in grup["kisimlar"]:
        yeni = dagilim[c.pk]
        if c.student_count != yeni:
            c.student_count = yeni
            c.save(update_fields=["student_count"])
    return True


def _sinif_duzeyi(deger):
    """"1", 1.0, "1. sınıf", "2.SNF" → 1 / 2; boş → None."""
    for ch in str(deger or ""):
        if ch.isdigit():
            return int(ch)
    return None


def kontenjanlari_aktar(school, dosya):
    """Program × sınıf kontenjanları (ya da programı olmayan kısımlar). Dönüş: (güncellenen, bulunamayanlar, hata)."""
    try:
        ws = _kitap(dosya).active
    except Exception:
        return 0, [], "Dosya okunamadı; .xlsx biçiminde Excel dosyası seçin."
    baslik, sutun = _sutunlar(ws, {"program": (["program"], False), "sinif": (["sınıf", "sinif", "düzey", "duzey"], False),
                                   "kisim": (["kısım", "kisim", "şube", "sube"], False),
                                   "kontenjan": (["kontenjan", "öğrenci", "ogrenci", "mevcut"], True)})
    if baslik is None or not ({"program", "kisim"} & set(sutun)):
        return 0, [], "Başlık satırında “Program”, “Sınıf” ve “Kontenjan” sütunları bulunamadı."
    classes = list(SchoolClass.objects.filter(school=school))
    gruplar = {(g["program"], g["sinif"]): g for g in program_gruplari(classes)[0]}
    kisimlar = {}
    for c in classes:
        for ad in (c.short, c.name):
            if ad:
                kisimlar.setdefault(_anahtar(ad), c)
    guncellenen, bulunamayan = 0, []
    for satir in ws.iter_rows(min_row=baslik + 1, values_only=True):
        try:
            sayi = max(0, int(float(satir[sutun["kontenjan"]])))
        except (TypeError, ValueError):
            continue
        program = kurallar.buyuk(str(satir[sutun["program"]] or "").strip()) if "program" in sutun else ""
        if program:
            sinif = _sinif_duzeyi(satir[sutun["sinif"]]) if "sinif" in sutun else None
            grup = gruplar.get((program, sinif))
            if grup is None:
                bulunamayan.append(f"{program} {sinif or '?'}. sınıf")
                continue
            program_kontenjani_yaz(grup, sayi)
            guncellenen += 1
            continue
        ad = satir[sutun["kisim"]] if "kisim" in sutun else None
        if ad in (None, ""):
            continue
        sinif = kisimlar.get(_anahtar(ad))
        if sinif is None:
            bulunamayan.append(str(ad))
            continue
        if sinif.student_count != sayi:
            sinif.student_count = sayi
            sinif.save(update_fields=["student_count"])
        guncellenen += 1
    return guncellenen, bulunamayan, None


def sayilari_yenile(school):
    """Kontenjan değişince okulun sınav dönemlerindeki (elle girilmemiş) sınav öğrenci sayıları."""
    from .models import ExamPeriod
    from .services import refresh_counts

    return sum(refresh_counts(p) for p in ExamPeriod.objects.filter(school=school))


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
        gruplar, programsiz = program_gruplari(classes)
        return _excel(["Program", "Sınıf", "Kısımlar", "Kontenjan"],
                      [[g["program"], g["sinif"], ", ".join(c.short or c.name for c in g["kisimlar"]), g["toplam"]]
                       for g in gruplar] + [["", "", c.short or c.name, c.student_count or 0] for c in programsiz],
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
        if action == "assign_programs":
            n = programlari_ata(classes)
            messages.success(request, f"{n} kısma program ve sınıf atandı." if n else "Atanacak kısım yok.")
            return redirect(back + "#kontenjan")
        if action == "save_quotas":
            gruplar, programsiz = program_gruplari(classes)
            n = 0
            for g in gruplar:
                try:
                    sayi = max(0, int(request.POST.get(f"kontenjan-{g['anahtar']}")))
                except (TypeError, ValueError):
                    continue
                n += program_kontenjani_yaz(g, sayi)
            for c in programsiz:
                try:
                    sayi = max(0, int(request.POST.get(f"kontenjan-{c.pk}")))
                except (TypeError, ValueError):
                    continue
                if (c.student_count or 0) != sayi:
                    c.student_count = sayi
                    c.save(update_fields=["student_count"])
                    n += 1
            if n:
                d = sayilari_yenile(school)
                messages.success(request, f"{n} kontenjan güncellendi; {d} sınavın öğrenci sayısı yeniden hesaplandı.")
            else:
                messages.success(request, "Değişiklik yok.")
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
                if action == "import_quotas":
                    ad = "kontenjan"
                    n_sinav = sayilari_yenile(school)
                    messages.info(request, f"{n_sinav} sınavın öğrenci sayısı yeniden hesaplandı.")
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
    gruplar, programsiz = program_gruplari(classes)
    return render(request, "sinav/courses.html", _nav(
        school, "sinav-bilgileri", rows=rows, classes=classes, turler=kurallar.SIK_TURLER, zorluklar=kurallar.ZORLUKLAR,
        eksik_tur=sum(1 for r in rows if not r["tur"]), uyg=sum(1 for r in rows if r["uyg"]),
        bos_kontenjan=sum(1 for c in classes if not c.student_count), gruplar=gruplar, programsiz=programsiz,
        atanabilir=sum(1 for c in programsiz if kurallar.kisim_bilgisi(c.short or c.name)[0]),
    ))
