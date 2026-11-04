from django.urls import path

from . import views

app_name = "personel"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("yeni/", views.ekle, name="ekle"),
    path("<int:pk>/", views.detay, name="detay"),
    path("<int:pk>/duzenle/", views.duzenle, name="duzenle"),
    path("<int:pk>/fotograf/", views.fotograf, name="fotograf"),
    path("<int:pk>/fotograf/yukle/", views.fotograf_yukle, name="fotograf_yukle"),
    path("kart-alanlari/", views.alanlar, name="alanlar"),
    path("teskilat/", views.teskilat, name="teskilat"),
    path("teskilat/<int:pk>/", views.teskilat_birimi, name="teskilat_birimi"),
]
