"""{% asset 'timetable/app.css' %}: statik dosya adresine içerik sürümü ekler (?v=…).

Tarayıcı CSS/JS'yi önbellekte uzun süre tutabilir; güncellemeden sonra eski stil yeni sayfalarla
karışmasın diye adres dosyanın içeriği değişince değişir."""

import hashlib

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()
_cache = {}


def version(path):
    found = finders.find(path)
    if not found:
        return ""
    try:
        import os

        mtime = os.stat(found).st_mtime
        if _cache.get(path, (None,))[0] != mtime:
            with open(found, "rb") as fh:
                _cache[path] = (mtime, hashlib.md5(fh.read()).hexdigest()[:10])
        return _cache[path][1]
    except OSError:
        return ""


@register.simple_tag
def asset(path):
    v = version(path)
    return static(path) + (f"?v={v}" if v else "")
