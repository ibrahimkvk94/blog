"""Yoklamada teşkilat birimleri: bir personelin birimi, bir birimin alt birimleri, kapsamdaki personel.

Personelin birimi: teşkilatta atandığı birim; atanmamışsa bölümünün "bölüm başkanlığı" birimi. Üst birim alt
birimlerini görür (şube müdürlüğü kısımlarını, bölüm başkanlıkları bölümleri …).
"""

from collections import defaultdict

from django.db.models import Q

from personel.models import TeskilatBirimi


class Birimsiz:
    """Teşkilatta yeri olmayan personel için sözde birim (yalnız tüm okulu görenlere)."""

    pk = id = 0
    ad = "Birimi belirsiz"
    tur = ""
    bolum = bolum_id = ust_id = None

    def get_tur_display(self):
        return "Teşkilatta yeri yok"

    def __eq__(self, diger):
        return isinstance(diger, Birimsiz)

    def __hash__(self):
        return 0

    def __str__(self):
        return self.ad


BIRIMSIZ = Birimsiz()


class Agac:
    def __init__(self):
        self.birimler = {b.pk: b for b in TeskilatBirimi.objects.filter(aktif=True).select_related("bolum")
                         .order_by("sira", "ad")}
        self.cocuklar = defaultdict(list)
        for b in self.birimler.values():
            ust = b.ust_id if b.ust_id in self.birimler else None
            self.cocuklar[ust].append(b)
        self.bolum_birimi = {b.bolum_id: b.pk for b in self.birimler.values() if b.bolum_id}

    def get(self, pk):
        if pk == 0:
            return BIRIMSIZ
        return self.birimler.get(pk)

    def bolumun(self, bolum_id):
        return self.birimler.get(self.bolum_birimi.get(bolum_id))

    def alt_idler(self, pk):
        """Birim ve tüm alt birimlerinin kimlikleri."""
        out, yigin = set(), [pk]
        while yigin:
            u = yigin.pop()
            if u in out:
                continue
            out.add(u)
            yigin.extend(c.pk for c in self.cocuklar.get(u, []))
        return out

    def zincir(self, pk):
        """Kökten birime kadar birimler."""
        z, b = [], self.birimler.get(pk)
        while b is not None and len(z) < 12:
            z.append(b)
            b = self.birimler.get(b.ust_id)
        return list(reversed(z))

    def kisi_birimi(self, p):
        """Personelin birim kimliği (0: teşkilatta yeri yok)."""
        if p.teskilat_birimi_id in self.birimler:
            return p.teskilat_birimi_id
        return self.bolum_birimi.get(p.bolum_id, 0)

    def kosul(self, idler):
        """Bu birimlerdeki personelin sorgu koşulu (0 → teşkilatta yeri olmayanlar)."""
        idler = set(idler)
        q = Q(teskilat_birimi_id__in=idler & set(self.birimler))
        bolumler = [bid for bid, pk in self.bolum_birimi.items() if pk in idler]
        yersiz = Q(teskilat_birimi__isnull=True) | ~Q(teskilat_birimi_id__in=list(self.birimler))
        if bolumler:
            q |= yersiz & Q(bolum_id__in=bolumler)
        if 0 in idler:
            q |= yersiz & (Q(bolum__isnull=True) | ~Q(bolum_id__in=list(self.bolum_birimi)))
        return q

    def sirali(self, kok_idler=None):
        """[(birim, derinlik)] — ağaç sırasıyla; kok_idler verilirse yalnız o kökler ve altları."""
        out = []

        def gez(b, d):
            out.append((b, d))
            for c in self.cocuklar.get(b.pk, []):
                gez(c, d + 1)

        kokler = self.cocuklar.get(None, []) if kok_idler is None else [self.birimler[k] for k in kok_idler
                                                                         if k in self.birimler]
        for k in kokler:
            gez(k, 0)
        return out
