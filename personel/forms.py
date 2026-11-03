from django import forms

from .models import Bolum, Personel, Secenek


class PersonelForm(forms.ModelForm):
    class Meta:
        model = Personel
        fields = ["ad_soyad", "personel_kodu", "sicil", "bolum", "unvan", "rutbe", "sinif", "aktif"]

    def __init__(self, *args, sabit_bolum=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bolum"].queryset = Bolum.objects.filter(aktif=True)
        # aSc'den gelen kayıtlarda bölüm boş olabilir; formda tamamlatılır
        self.fields["bolum"].required = True
        for alan, tur in (("rutbe", Secenek.RUTBE), ("sinif", Secenek.SINIF), ("unvan", Secenek.UNVAN)):
            self.fields[alan].queryset = Secenek.objects.filter(tur=tur, aktif=True)
        if sabit_bolum is not None:
            # Sadece kendi bölümünde yetkili kullanıcı başka bölüme personel ekleyemez/taşıyamaz
            self.fields["bolum"].queryset = Bolum.objects.filter(pk=sabit_bolum.pk)
            self.fields["bolum"].initial = sabit_bolum
            self.fields["bolum"].disabled = True
        for f in self.fields.values():
            css = "form-check-input" if isinstance(f.widget, forms.CheckboxInput) else (
                "form-select" if isinstance(f.widget, forms.Select) else "form-control"
            )
            f.widget.attrs["class"] = css
