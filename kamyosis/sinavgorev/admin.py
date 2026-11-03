from django.contrib import admin

from .models import IslenenDonem, SinavGorevi


@admin.register(SinavGorevi)
class SinavGoreviAdmin(admin.ModelAdmin):
    list_display = ["personel", "tarih", "saat", "rol", "sinav", "salon", "donem_adi", "elle"]
    list_filter = ["rol", "elle", "donem_adi", "personel__bolum"]
    search_fields = ["personel__ad_soyad", "sinav"]
    raw_id_fields = ["personel"]
    readonly_fields = ["sinav_donemi", "ekleyen", "olusturma"]
    date_hierarchy = "tarih"


@admin.register(IslenenDonem)
class IslenenDonemAdmin(admin.ModelAdmin):
    list_display = ["sinav_donemi", "gorev_sayisi", "isleyen", "zaman"]
    readonly_fields = ["sinav_donemi", "gorev_sayisi", "isleyen", "zaman"]
