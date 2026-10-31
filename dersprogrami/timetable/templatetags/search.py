"""Arama anahtarı: Türkçe büyük/küçük harf ve şapka/nokta farkı gözetmeyen metin (tarayıcıdaki aramayla aynı)."""

from django import template

from timetable.textsort import search_fold

register = template.Library()
register.filter("fold", search_fold)
