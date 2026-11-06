"""Yoklama raporu (Excel): günlük özet, kayıtlar ve kişi özeti."""

import datetime
from collections import defaultdict

from django.http import HttpResponse
from django.utils import timezone

from . import servis
from .models import IzinTuru


def excel(bas_tarih, bit_tarih, kisiler, bolum=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    turler = list(IzinTuru.objects.filter(mevcut_sayilir=False))
    gunler = [bas_tarih + datetime.timedelta(days=i) for i in range((bit_tarih - bas_tarih).days + 1)]
    bas, bit = servis.gun_araligi(bas_tarih)[0], servis.gun_araligi(bit_tarih)[1]
    kayitlar = servis.kayitlar([p.pk for p in kisiler], bas, bit, yoklama=True)
    kalin = Font(bold=True, color="FFFFFF")
    zemin = PatternFill("solid", fgColor="1F3A5F")

    def baslik(ws, satir):
        ws.append(satir)
        for c in ws[ws.max_row]:
            c.font, c.fill = kalin, zemin
            c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.freeze_panes = ws.cell(row=ws.max_row + 1, column=1)

    def genislik(ws, olculer):
        for i, w in enumerate(olculer, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w

    wb = Workbook()
    ws = wb.active
    ws.title = "Günlük özet"
    ws.append([f"Personel yoklaması {bas_tarih:%d.%m.%Y} – {bit_tarih:%d.%m.%Y}" + (f" · {bolum.ad}" if bolum else "")])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Oluşturma: {timezone.localtime():%d.%m.%Y %H:%M}. Gün boyu yok = günü tamamen kaplayan kayıt; "
               "kısmi = gün içinde saatlik kayıt."])
    ws.append([])
    baslik(ws, ["Tarih", "Gün", "Bölüm", "Toplam", "Mevcut", "Gün boyu yok", "Kısmi"] + [t.ad for t in turler])
    gun_adlari = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    by_bolum = defaultdict(list)
    for p in kisiler:
        by_bolum[p.bolum].append(p)
    by_kisi = defaultdict(list)
    for k in kayitlar:
        by_kisi[k.personel_id].append(k)
    for g in gunler:
        gb, gs = servis.gun_araligi(g)
        for b, ps in sorted(by_bolum.items(), key=lambda kv: getattr(kv[0], "ad", "")):
            yok = kismi = 0
            tur_sayi = defaultdict(int)
            for p in ps:
                hk = [k for k in by_kisi.get(p.pk, []) if k.baslangic < gs and k.bitis > gb]
                if not hk:
                    continue
                if any(k.baslangic <= gb and k.bitis >= gs for k in hk):
                    yok += 1
                else:
                    kismi += 1
                for tid in {k.tur_id for k in hk}:
                    tur_sayi[tid] += 1
            ws.append([g, gun_adlari[g.weekday()], getattr(b, "ad", "Bölümsüz"), len(ps), len(ps) - yok, yok, kismi]
                      + [tur_sayi.get(t.pk, 0) or None for t in turler])
            ws.cell(row=ws.max_row, column=1).number_format = "DD.MM.YYYY"
    genislik(ws, [12, 11, 30, 9, 9, 12, 8] + [12] * len(turler))

    ws = wb.create_sheet("Kayıtlar")
    baslik(ws, ["Personel", "Künye", "Bölüm", "Tür", "Başlangıç", "Bitiş", "Süre", "Açıklama", "Giren", "Giriş zamanı"])
    for k in kayitlar:
        p = k.personel
        sure = f"{k.gun_sayisi} gün" if k.tam_gun else f"{(k.bitis - k.baslangic).total_seconds() / 3600:g} saat"
        ws.append([p.ad_soyad, p.kunye, getattr(p.bolum, "ad", ""), k.tur.ad, k.yerel_bas.replace(tzinfo=None),
                   (k.son_gun if k.tam_gun else k.yerel_bit.replace(tzinfo=None)), sure, k.aciklama,
                   str(k.olusturan or ""), timezone.localtime(k.olusturma).replace(tzinfo=None)])
        ws.cell(row=ws.max_row, column=5).number_format = "DD.MM.YYYY" if k.tam_gun else "DD.MM.YYYY HH:MM"
        ws.cell(row=ws.max_row, column=6).number_format = "DD.MM.YYYY" if k.tam_gun else "DD.MM.YYYY HH:MM"
        ws.cell(row=ws.max_row, column=10).number_format = "DD.MM.YYYY HH:MM"
    genislik(ws, [26, 22, 26, 18, 17, 17, 10, 34, 14, 17])

    ws = wb.create_sheet("Kişi özeti")
    baslik(ws, ["Personel", "Künye", "Bölüm"] + [f"{t.ad} (gün)" for t in turler] + ["Saatlik (saat)"])
    for p in kisiler:
        ks = by_kisi.get(p.pk, [])
        if not ks:
            continue
        gun = defaultdict(int)
        saat = 0.0
        for k in ks:
            if k.tam_gun:  # aralık içine düşen günler
                ilk, son = max(k.yerel_bas.date(), bas_tarih), min(k.son_gun, bit_tarih)
                gun[k.tur_id] += max(0, (son - ilk).days + 1)
            else:
                saat += (min(k.bitis, bit) - max(k.baslangic, bas)).total_seconds() / 3600
        ws.append([p.ad_soyad, p.kunye, getattr(p.bolum, "ad", "")] + [gun.get(t.pk) or None for t in turler]
                  + [round(saat, 2) or None])
    genislik(ws, [26, 22, 26] + [14] * (len(turler) + 1))

    yanit = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    ad = f"personel_yoklamasi_{bas_tarih:%Y%m%d}_{bit_tarih:%Y%m%d}.xlsx"
    yanit["Content-Disposition"] = f'attachment; filename="{ad}"'
    wb.save(yanit)
    return yanit
