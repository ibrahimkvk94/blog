from django import forms
from .models import Iletisim
from captcha.fields import ReCaptchaField

class MesajForm(forms.ModelForm):
    #captcha = ReCaptchaField()
    class Meta:
        model =Iletisim
        fields = ['isim',
                  'mail',
                  'konu',
                  'mesaj',
        ]

