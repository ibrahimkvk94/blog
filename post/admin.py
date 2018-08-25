from django.contrib import admin
from .models import Post

# Register your models here.

class PostAdmin(admin.ModelAdmin):

    list_display = ['baslik','tarih','slug']
    list_display_links = ['baslik','tarih']
    list_filter = ['tarih']
    search_fields =['baslik','metin']

    #list_editable = ['baslik']
    class Meta:
        model = Post



admin.site.register(Post, PostAdmin)