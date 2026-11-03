from django.contrib import admin

from .models import Bolum, Personel, Secenek


@admin.register(Bolum)
class BolumAdmin(admin.ModelAdmin):
    list_display = ["ad", "kod", "ders_onekleri", "aktif"]
    list_editable = ["aktif"]
    search_fields = ["ad", "kod"]


@admin.register(Secenek)
class SecenekAdmin(admin.ModelAdmin):
    list_display = ["metin", "tur", "one_cikan", "sira", "aktif"]
    list_filter = ["tur", "aktif"]
    list_editable = ["one_cikan", "sira", "aktif"]
    search_fields = ["metin"]


@admin.register(Personel)
class PersonelAdmin(admin.ModelAdmin):
    list_display = ["ad_soyad", "personel_kodu", "bolum", "rutbe", "unvan", "aktif"]
    list_filter = ["aktif", "bolum", "rutbe", "unvan"]
    search_fields = ["ad_soyad", "personel_kodu", "sicil"]
