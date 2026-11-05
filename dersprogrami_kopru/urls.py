from django.urls import path

from . import views

app_name = "dersprogrami_kopru"

urlpatterns = [
    path("sinavlar/", views.sinavlar, name="sinavlar"),
    path("ac/", views.cerceve, name="cerceve"),
]
