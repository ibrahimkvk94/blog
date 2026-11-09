"""Müsait personel sayfası (İdari İşler · Müsait Personel). Sorgu GET ile yapılır; bağlantı paylaşılabilir."""

import datetime
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from core.yetki import birim_bul, yol

from . import musait
from .birim import BIRIMSIZ


def _tarih(metin):
    try:
        return datetime.date.fromisoformat(metin or "")
    except ValueError:
        return None


def _saat(metin):
    try:
        return datetime.time.fromisoformat(metin or "")
    except ValueError:
        return None


def _ders_saatleri():
    """Geçerli ders programının ders saatleri (formdaki hızlı seçim düğmeleri için)."""
    from program.models import DersSaati, ProgramSurumu

    surum = ProgramSurumu.objects.gecerli() or ProgramSurumu.objects.order_by("-pk").first()
    if surum is None:
        return []
    return list(DersSaati.objects.filter(surum=surum).exclude(baslangic=None).exclude(bitis=None).order_by("no"))


@login_required
def musait_personel(request):
    y = musait.yetki(request)
    if not y.goruntule:
        raise PermissionDenied
    request.birim = birim_bul(request, musait.BIRIM)
    g = request.GET
    tarih = _tarih(g.get("tarih"))
    bas, bit = _saat(g.get("bas")), _saat(g.get("bit"))
    kategoriler = [k for k in g.getlist("k") if k in musait.KATEGORI_ADI]
    sinav = g.get("sinav", "1") == "1" if "tarih" in g else True
    birimler = [(b, d) for b, d in y.agac.sirali([y.kapsam_birim.pk] if y.kapsam_birim else None)]
    birim = None
    if g.get("birim", "").isdigit():
        birim = next((b for b, _ in birimler if b.pk == int(g["birim"])), None)
    elif g.get("birim") == "yok" and y.kapsam_birim is None:
        birim = BIRIMSIZ

    ctx = {"yol": yol(request, request.birim), "kategoriler": musait.KATEGORILER,
           "secili_k": kategoriler, "tarih": tarih or timezone.localdate(), "bas": bas, "bit": bit, "sinav": sinav,
           "birimler": birimler, "secili_birim": birim, "tum_okul": y.kapsam_birim is None,
           "ders_saatleri": _ders_saatleri(), "sorgu": False}
    if "tarih" in g:
        if tarih is None or bas is None or bit is None:
            ctx["hata"] = "Günü, başlangıç ve bitiş saatini seçin."
        elif bit <= bas:
            ctx["hata"] = "Bitiş saati başlangıçtan sonra olmalı."
        else:
            kisiler = musait.sorgula(y, tarih, bas, bit, kategoriler or None, birim, sinav)
            musaitler = [k for k in kisiler if k.musait]
            if g.get("excel") == "1":
                return _excel(musaitler, tarih, bas, bit, kategoriler)
            ctx.update(sorgu=True, ozet=musait.ozet(kisiler), musait_gruplar=musait.gruplu(musaitler, y.agac),
                       mesguller=[k for k in kisiler if not k.musait])
    return render(request, "yoklama/musait.html", ctx)


def _excel(kisiler, tarih, bas, bit, kategoriler):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Müsait personel"
    kat = ", ".join(musait.KATEGORI_ADI[k] for k in kategoriler) or "Tüm personel"
    ws.append([f"{tarih:%d.%m.%Y} {bas:%H:%M}–{bit:%H:%M} arası müsait personel ({kat}): {len(kisiler)} kişi"])
    ws["A1"].font = Font(bold=True)
    ws.append([])
    ws.append(["S.N.", "Ad soyad", "Rütbe / unvan", "Sınıf", "Kategori", "Birim"])
    for c in ws[3]:
        c.font = Font(bold=True)
    for i, k in enumerate(kisiler, 1):
        p = k.personel
        ws.append([i, p.ad_soyad, str(p.rutbe or p.unvan or ""), str(p.sinif or ""), k.kategori_adi, str(k.birim)])
    for sutun, gen in zip("ABCDEF", (6, 30, 18, 14, 22, 40)):
        ws.column_dimensions[sutun].width = gen
    yanit = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    ad = f"Müsait personel {tarih:%d.%m.%Y} {bas:%H%M}-{bit:%H%M}.xlsx"
    yanit["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(ad)}"
    wb.save(yanit)
    return yanit
