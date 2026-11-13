from django.contrib import admin

from .models import Brans, Program, Yil


@admin.register(Yil)
class YilAdmin(admin.ModelAdmin):
    list_display = ["ad", "varsayilan", "uyari_esigi"]


@admin.register(Brans)
class BransAdmin(admin.ModelAdmin):
    list_display = ["ad", "grup", "sira", "hesapta"]
    list_editable = ["grup", "sira", "hesapta"]


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ["ad", "kod", "yil", "kisim1", "kisim2"]
    list_filter = ["yil"]
