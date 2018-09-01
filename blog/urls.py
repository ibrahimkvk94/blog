from django.conf.urls import url, include
from django.contrib import admin
from home.views import *
from django.conf.urls.static import static
from django.conf import settings
from mail import views


urlpatterns = [

    url(r'^$', home_view, name='home'),
    url(r'^hakkimda/', hakkimda_view, name='hakkimda'),
    url(r'^post/', include('post.urls')),
    url(r'^photo/', include('photo.urls')),
    url(r'^abone/', views.abone_create),
    url(r'^send/', views.mail_sender),
    url(r'^admin/', admin.site.urls),
    url(r'^dosyalar/', include('dosya.urls'), name='dosya'),
    url(r'^iletisim/', include('iletisim.urls'), name='iletisim'),
    url(r'^photos/', include('photos.urls', namespace='photos')),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)