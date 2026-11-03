from django.contrib.auth import views as auth_views
from django.urls import path

from .views import ParolaDegistirView

urlpatterns = [
    path("giris/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("cikis/", auth_views.LogoutView.as_view(), name="logout"),
    path("parola/", ParolaDegistirView.as_view(), name="parola_degistir"),
]
