from django.contrib import admin

from .models import GunlukOnay, IzinTuru, YoklamaGecmisi, YoklamaKaydi


@admin.register(IzinTuru)
class IzinTuruAdmin(admin.ModelAdmin):
    list_display = ["ad", "kisa", "renk", "sira", "aktif"]
    list_editable = ["sira", "aktif"]


@admin.register(YoklamaKaydi)
class YoklamaKaydiAdmin(admin.ModelAdmin):
    list_display = ["personel", "tur", "baslangic", "bitis", "olusturan", "guncelleme"]
    list_filter = ["tur", "personel__bolum"]
    search_fields = ["personel__ad_soyad", "aciklama"]
    raw_id_fields = ["personel"]
    readonly_fields = ["olusturan", "olusturma", "guncelleyen", "guncelleme", "surum"]
    date_hierarchy = "baslangic"


@admin.register(GunlukOnay)
class GunlukOnayAdmin(admin.ModelAdmin):
    list_display = ["bolum", "tarih", "onaylayan", "zaman", "degisti"]
    list_filter = ["bolum"]
    date_hierarchy = "tarih"


@admin.register(YoklamaGecmisi)
class YoklamaGecmisiAdmin(admin.ModelAdmin):
    list_display = ["zaman", "personel", "islem", "ozet", "kullanici", "onay_sonrasi"]
    list_filter = ["islem", "onay_sonrasi"]
    search_fields = ["personel__ad_soyad", "ozet"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
