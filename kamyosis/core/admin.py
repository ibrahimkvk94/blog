from django.contrib import admin

from .models import Birim, Yetki


class AltBirimInline(admin.TabularInline):
    model = Birim
    fk_name = "ust"
    fields = ["ad", "slug", "tur", "sira", "durum", "aktif"]
    extra = 0
    show_change_link = True


@admin.register(Birim)
class BirimAdmin(admin.ModelAdmin):
    list_display = ["ad", "ust", "tur", "sira", "durum", "aktif"]
    list_filter = ["tur", "durum", "aktif", "ust"]
    list_editable = ["sira", "durum", "aktif"]
    search_fields = ["ad", "slug"]
    prepopulated_fields = {"slug": ["ad"]}
    inlines = [AltBirimInline]


@admin.register(Yetki)
class YetkiAdmin(admin.ModelAdmin):
    list_display = ["kullanici", "birim", "seviye", "kapsam"]
    list_filter = ["seviye", "kapsam", "birim"]
    search_fields = ["kullanici__username", "kullanici__first_name", "kullanici__last_name"]
    autocomplete_fields = ["kullanici", "birim"]
