from django.urls import path

from . import views

app_name = "isler"

urlpatterns = [
    path("", views.liste, name="liste"),
]
