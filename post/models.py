from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from ckeditor.fields import RichTextField
from mail.models import Abone
from django.core.mail import send_mail
from mail.views import mail_sender
# Create your models here.

class Post(models.Model):
    user = models.ForeignKey('auth.User', verbose_name="Yazar", related_name='posts')
    baslik = models.CharField(max_length=120, verbose_name='Başlık')
    kategori = models.CharField(max_length=120, verbose_name='Kategori(Eğitim/Yazı/video)')
    link =   models.CharField(max_length=420,verbose_name="Video link",null=True)
    metin = RichTextField(verbose_name='Metin')
    tarih = models.DateField(verbose_name='Tarih',auto_now_add=True)
    image = models.ImageField(null=True, blank=True)
    slug = models.SlugField(unique=True,editable=False,max_length=130)
    like = models.IntegerField(verbose_name="like",editable=False, default =0)
    comment = models.IntegerField(verbose_name="like",editable=False, default =1)
    look = models.IntegerField(verbose_name="like",editable=False,default =0)
    tags = models.CharField(max_length=300, verbose_name="Taglar , ile ayır")
    

    def screenshots_as_list(self):
        return self.tags.split(',')

    def __str__(self):
        return self.baslik

    def get_absolute_url(self):
        return reverse('post:detay', kwargs={'slug': self.slug})

    def get_create_url(self):
        return reverse('post:create')

    def get_update_url(self):
        return reverse('post:update', kwargs={'slug': self.slug})

    def get_delete_url(self):
        return reverse('post:delete', kwargs={'slug': self.slug})

    def get_unique_slug(self):
        slug = slugify(self.baslik.replace('ı','i'))
        unique_slug = slug
        return unique_slug



    def save(self, *args,**kwargs):
        self.slug = self.get_unique_slug()
        abone_list = Abone.objects.all()
        for i in abone_list:
            mail_sender(i)
        return super(Post, self).save(*args,**kwargs)


    class Meta:
        ordering =['-tarih', '-id']

class Comment(models.Model):
    post = models.ForeignKey('post.Post',related_name='comments', on_delete=models.CASCADE)
    name = models.CharField(max_length =200, verbose_name='İsim')
    content = models.TextField(verbose_name='Yorum')
    created_date =models.DateTimeField(auto_now_add = True)
