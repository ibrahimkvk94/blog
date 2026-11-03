from django.urls import path

from . import views

app_name = "personel"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("yeni/", views.ekle, name="ekle"),
    path("<int:pk>/", views.detay, name="detay"),
    path("<int:pk>/duzenle/", views.duzenle, name="duzenle"),
]
