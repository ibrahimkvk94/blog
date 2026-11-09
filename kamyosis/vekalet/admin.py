from django.contrib import admin

from .models import Vekalet


@admin.register(Vekalet)
class VekaletAdmin(admin.ModelAdmin):
    list_display = ("veren", "vekil", "gorev", "baslangic", "bitis", "sonlandirma")
    list_filter = ("neden",)
    search_fields = ("veren__ad_soyad", "vekil__ad_soyad", "gorev")
    raw_id_fields = ("veren", "vekil")
