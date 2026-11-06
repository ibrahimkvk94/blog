from django.contrib.auth import views as auth_views
from django.urls import path

from .views import GirisView, ParolaDegistirView, giris_kodu, iki_adim_ayari

urlpatterns = [
    path("giris/", GirisView.as_view(), name="login"),
    path("giris/kod/", giris_kodu, name="giris_kodu"),
    path("cikis/", auth_views.LogoutView.as_view(), name="logout"),
    path("parola/", ParolaDegistirView.as_view(), name="parola_degistir"),
    path("iki-adimli-dogrulama/", iki_adim_ayari, name="iki_adim"),
]
