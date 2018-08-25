from django import forms
from .models import Abone
from captcha.fields import ReCaptchaField

class AboneForm(forms.ModelForm):
    #captcha = ReCaptchaField()
    class Meta:
        model = Abone
        fields = ['mail']