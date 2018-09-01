from django.conf.urls import url
from .views import *
from . import views

app_name = 'post'
urlpatterns = [

    url(r'^index/$', post_index, name="index"),
    url(r'^(?P<slug>[\w-]+)/like/$', like, name="like"),
    url(r'^create/$', post_create, name='create'),

    url(r'^(?P<slug>[\w-]+)/$', post_detail, name='detay'),
    url(r'^(?P<slug>[\w-]+)/update/$', post_update, name="update"),
    url(r'^(?P<slug>[\w-]+)/delete/$', post_delete, name='delete'),

]

