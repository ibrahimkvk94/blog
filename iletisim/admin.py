from django.contrib import admin
from .models import Iletisim

# Register your models here.
def make_published(modeladmin, request, queryset):
    queryset.update(completed = 'True')
make_published.short_description = "Okundu"


class Mesajadmin(admin.ModelAdmin):

    list_display = ['isim','konu','tarih','mail','completed']
    list_display_links = ['isim','konu','tarih']
    list_filter = ['tarih','completed']
    search_fields =['isim','mesaj','konu']
    actions = [make_published]
    #list_editable = ['baslik']
    class Meta:
        model = Iletisim

admin.site.register(Iletisim, Mesajadmin)