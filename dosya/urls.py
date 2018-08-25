from django.conf.urls import url
from .views import *


app_name = 'dosya'
urlpatterns = [

    url(r'^index/$', dosya_index, name="index"),


]

