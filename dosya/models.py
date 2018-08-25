from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from ckeditor.fields import RichTextField

# Create your models here.

class Dosya(models.Model):
    user = models.ForeignKey('auth.User', verbose_name="Yazar", related_name='dosyas')
    baslik = models.CharField(max_length=120, verbose_name='Başlık')
    metin = RichTextField(max_length=460, verbose_name="Özeti")
    tarih = models.DateField(verbose_name='Tarih',auto_now_add=True)
    dosya = models.FileField(null=True, blank=True)



    def __str__(self):
        return self.baslik
    class Meta:
        ordering =['-tarih', '-id']
