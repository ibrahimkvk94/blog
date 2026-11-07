from django.urls import path

from . import kullanici_views as kv
from . import views

app_name = "core"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("organizasyon/", views.organizasyon, name="organizasyon"),
    path("bolum-yetkileri/", views.bolum_yetkileri, name="bolum_yetkileri"),
    path("bolum-kisayollari/", views.bolum_kisayollari, name="bolum_kisayollari"),
    path("kullanicilar/", kv.kullanicilar, name="kullanicilar"),
    path("kullanicilar/yeni/", kv.kullanici_yeni, name="kullanici_yeni"),
    path("kullanicilar/gecmis/", kv.kullanici_gecmisi, name="kullanici_gecmisi"),
    path("kullanicilar/<int:pk>/", kv.kullanici, name="kullanici"),
    path("birim/<slug:slug>/", views.birim, name="birim"),
]
