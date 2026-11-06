from django.urls import path

from . import views

app_name = "ogrenci"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("excel/", views.excel, name="excel"),
    path("yeni/", views.duzenle, name="ekle"),
    path("<int:pk>/", views.duzenle, name="duzenle"),
    path("kare-kod/", views.karekod, name="karekod"),
    path("kare-kod/okuyucu/", views.okuyucu_indir, name="okuyucu"),
    path("bilgi-formu/", views.bilgi_formu, name="bilgi_formu"),
]
