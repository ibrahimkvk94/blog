from django.urls import path

from . import views

app_name = "bildirim"

urlpatterns = [
    path("durum/", views.durum, name="durum"),
    path("liste/", views.liste, name="liste"),
    path("ayarlar/", views.ayarlar, name="ayarlar"),
    path("tercih/", views.tercih, name="tercih"),
    path("okundu/", views.okundu, name="okundu"),
    path("<int:pk>/", views.ac, name="ac"),
]
