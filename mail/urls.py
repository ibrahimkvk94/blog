from django.conf.urls import url
from .views import *


app_name = 'mail'
urlpatterns = [

   
    url(r'^create/$', abone_create),
     url(r'^send/$', mail_sender),
]