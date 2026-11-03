from django.urls import path

from . import views

app_name = "program"

urlpatterns = [
    path("", views.ana, name="ana"),
    path("tablo/", views.tablo, name="tablo"),
    path("surumler/", views.surumler, name="surumler"),
    path("surumler/<int:pk>/", views.surum, name="surum"),
    path("ogretmenler/", views.ogretmenler, name="ogretmenler"),
    path("ogretmenler/toplu-ekle/", views.ogretmen_toplu, name="ogretmen_toplu"),
    path("ogretmenler/<int:pk>/", views.ogretmen_islem, name="ogretmen_islem"),
]
