from django.contrib import admin

from .models import Ders, Derslik, Grup, Kisim, ProgramOgretmeni, ProgramSurumu


@admin.register(ProgramSurumu)
class ProgramSurumuAdmin(admin.ModelAdmin):
    list_display = ["ad", "durum", "baslangic", "bitis", "yukleme_zamani", "yukleyen"]
    list_filter = ["durum"]


@admin.register(Ders)
class DersAdmin(admin.ModelAdmin):
    list_display = ["kod", "ad", "bolum", "sinif"]
    list_filter = ["bolum", "sinif"]
    search_fields = ["kod", "ad"]


@admin.register(Kisim)
class KisimAdmin(admin.ModelAdmin):
    list_display = ["kod", "ad", "tur", "bolum", "sinif"]
    list_filter = ["tur", "bolum", "sinif"]
    list_editable = ["tur", "bolum", "sinif"]
    search_fields = ["kod", "ad"]


@admin.register(Grup)
class GrupAdmin(admin.ModelAdmin):
    list_display = ["kisim", "ad", "tum_kisim", "bolunme"]
    list_filter = ["tum_kisim", "bolunme"]


@admin.register(Derslik)
class DerslikAdmin(admin.ModelAdmin):
    list_display = ["ad", "kapasite", "aktif"]
    list_editable = ["kapasite", "aktif"]
    search_fields = ["ad"]


@admin.register(ProgramOgretmeni)
class ProgramOgretmeniAdmin(admin.ModelAdmin):
    list_display = ["ad", "kisa_ad", "personel", "durum", "tahmini_bolum"]
    list_filter = ["durum", "tahmini_bolum"]
    search_fields = ["ad", "kisa_ad", "personel__ad_soyad"]
    autocomplete_fields = ["personel"]
