"""Türkçe harf ve büyük-küçük harf duyarsız arama.

SQLite'ın büyük-küçük harf eşleştirmesi yalnız İngilizce harfleri tanır ("girgen" ≠ "GİRGEN"). Veritabanına
`tr_sade()` işlevi eklenir: metni küçültür, Türkçe harfleri sadeleştirir (İ/I/ı→i, ş→s, ğ→g, ç→c, ö→o, ü→u) ve
aksanları atar. Arama sözcüklere bölünür; her sözcük alanlardan birinde geçmelidir ("mehmet girgen" =
"girgen mehmet").

    from core.arama import ara
    qs = ara(qs, request.GET.get("q"), "ad_soyad", "sicil")
"""

import unicodedata

from django.db.models import CharField, Func, Q

_TABLO = str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ç": "c", "ö": "o", "ü": "u", "â": "a", "î": "i", "û": "u"})


def sade(metin):
    if metin is None:
        return ""
    metin = str(metin).replace("İ", "i").replace("I", "ı").lower().translate(_TABLO)
    metin = unicodedata.normalize("NFD", metin)
    return "".join(c for c in metin if not unicodedata.combining(c))


class TrSade(Func):
    function = "tr_sade"
    output_field = CharField()


def ara(qs, q, *alanlar):
    """qs'i q'daki her sözcüğün alanlardan birinde (Türkçe harf / büyük-küçük harf duyarsız) geçtiği kayıtlara süzer."""
    sozcukler = sade(q).split()
    if not sozcukler or not alanlar:
        return qs
    adlar = {alan: f"_ara_{i}" for i, alan in enumerate(alanlar)}
    qs = qs.annotate(**{ad: TrSade(alan) for alan, ad in adlar.items()})
    for s in sozcukler:
        kosul = Q()
        for ad in adlar.values():
            kosul |= Q(**{f"{ad}__contains": s})
        qs = qs.filter(kosul)
    return qs


def eslesir(q, *metinler):
    """Bellekteki liste için aynı kural: q'nun her sözcüğü metinlerden birinde geçiyor mu?"""
    sozcukler = sade(q).split()
    sadeler = [sade(m) for m in metinler]
    return all(any(s in m for m in sadeler) for s in sozcukler)


def baglanti_kuruldu(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        connection.connection.create_function("tr_sade", 1, sade, deterministic=True)
