from django.contrib import admin

from .models import Salon, SalonKaydi


@admin.register(Salon)
class SalonAdmin(admin.ModelAdmin):
    list_display = ["ad", "kisa", "renk", "kapasite", "sira", "aktif"]
    list_editable = ["sira", "aktif"]


@admin.register(SalonKaydi)
class SalonKaydiAdmin(admin.ModelAdmin):
    list_display = ["tarih", "salon", "saat_metni", "baslik", "olusturan"]
    list_filter = ["salon"]
    date_hierarchy = "tarih"
    search_fields = ["baslik", "aciklama"]
