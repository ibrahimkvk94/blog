from django.conf.urls import url
from .views import *


app_name = 'iletisim'
urlpatterns = [

    url(r'^index/$', iletisim_index, name="index"),
     url(r'^send/$', send_email, name="send"),


]

