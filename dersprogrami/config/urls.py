from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("sinav-planlama/", include("sinav.urls")),
    path("", include("timetable.urls")),
]
