from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from ckeditor.fields import RichTextField
from django.core.mail import send_mail




class Iletisim(models.Model):
    isim = models.CharField(max_length=195, verbose_name='İsim')
    mail = models.CharField(max_length=195, verbose_name='e-mail')
    konu = models.CharField(max_length=195, verbose_name='Konu')
    mesaj = RichTextField(verbose_name='Mesaj')
    tarih = models.DateField(verbose_name='Tarih',auto_now_add=True)
    comment = models.IntegerField(verbose_name="like",editable=False, default =1)
    completed = models.BooleanField(verbose_name="Durum", default="False")

    def __str__(self):
        return self.isim

    def get_absolute_url(self):
        return reverse('iletisim:index')

    def save(self, *args,**kwargs):
        send_mail('ibrahimkavak.com da yeni İletişim İsteği.',
        'İletişim formuna yeni mesaj var. <br>Okumak için ibrahimkavak.com ziyaret ediniz.',
        'ibrahimkvk94@gmail.com',
        ["ibrahimkvk94@gmail.com"],
        fail_silently=False)
        return super(Iletisim, self).save(*args,**kwargs)


    class Meta:
        ordering =['-tarih', '-id']

