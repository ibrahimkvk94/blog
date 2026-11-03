from django.urls import path

from . import views

app_name = "mazeret"

urlpatterns = [
    path("ders/", views.ders, name="ders"),
    path("ders/<int:donem_pk>/personel/<int:personel_pk>/", views.bildirim, name="bildirim"),
    path("ders/<int:donem_pk>/toplu/", views.toplu, name="toplu"),
    path("ders/<int:donem_pk>/aktar/", views.aktar, name="aktar"),
]
