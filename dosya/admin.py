from django.contrib import admin
from .models import Dosya

# Register your models here.
class DosyaAdmin(admin.ModelAdmin):

    list_display = ['baslik','tarih']
    list_display_links = ['baslik','tarih']
    list_filter = ['tarih']
    search_fields =['baslik','metin']

    #list_editable = ['baslik']
    class Meta:
        model = Dosya



admin.site.register(Dosya, DosyaAdmin)