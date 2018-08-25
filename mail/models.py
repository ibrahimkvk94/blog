from django.db import models
from django.urls import reverse
# Create your models here.


class Abone(models.Model):
    mail = models.CharField(max_length=170, verbose_name='mail')
    status = models.BooleanField(verbose_name="Durum", default="False")
    def __str__(self):
        return self.mail
        
