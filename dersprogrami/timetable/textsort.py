"""Türkçe doğal sıralama: harfler Türk alfabesine göre (Ç, Ğ, I/İ, Ö, Ş, Ü yerinde), sayılar değerine göre
("2.KISIM" "10.KISIM"dan önce)."""

import re

TR_ALPHABET = "abcçdefgğhıijklmnoöprsştuüvyz"
_ORDER = {ch: i for i, ch in enumerate(TR_ALPHABET)}
_PARTS = re.compile(r"(\d+)")


def tr_lower(text):
    return (text or "").replace("I", "ı").replace("İ", "i").lower()


def tr_key(text):
    """Yalnızca harf sırası (sayılar karakter olarak)."""
    return [_ORDER.get(ch, 100 + ord(ch)) for ch in tr_lower(text)]


def natural_key(text):
    """Doğal sıralama anahtarı: metin parçaları Türkçe harf sırasıyla, sayı parçaları değeriyle karşılaştırılır."""
    key = []
    for i, part in enumerate(_PARTS.split(tr_lower(text).strip())):
        if not part:
            continue
        key.append((0, int(part), []) if i % 2 else (1, 0, tr_key(part)))  # sayılar harflerden önce
    return key
