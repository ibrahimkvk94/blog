from django.urls import path

from . import views

app_name = "ogrenci"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("excel/", views.excel, name="excel"),
    path("yeni/", views.duzenle, name="ekle"),
    path("<int:pk>/", views.duzenle, name="duzenle"),
]
