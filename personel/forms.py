from django import forms

from .models import Bolum, KartAlani, Personel, Secenek, TeskilatBirimi

YONETICI_ALANLARI = ["personel_kodu", "derse_girebilir", "sinav_gorevi_alabilir", "teskilat_birimi", "gorev_unvani",
                     "idari_kadro"]


class PersonelForm(forms.ModelForm):
    """Temel bilgiler herkese (yetkisi kadar); T.C. kimlik no, ders/sınav kullanımı, teşkilat ve idari kadro yalnız
    yöneticilere (Personel Kartları biriminde yönetim yetkisi)."""

    class Meta:
        model = Personel
        fields = ["ad_soyad", "sicil", "bolum", "unvan", "rutbe", "sinif", "aktif", *YONETICI_ALANLARI]

    def __init__(self, *args, sabit_bolum=None, yonetici=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not yonetici:
            for alan in YONETICI_ALANLARI:
                self.fields.pop(alan)
        else:
            self.fields["teskilat_birimi"].queryset = TeskilatBirimi.objects.filter(aktif=True).exclude(
                tur__in=[TeskilatBirimi.BOLUM, TeskilatBirimi.BASKANLIKLAR])
            self.fields["teskilat_birimi"].empty_label = "Bölümüne göre (bölüm başkanlığı)"
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


class KartAlaniFormu(forms.ModelForm):
    class Meta:
        model = KartAlani
        fields = ["ad", "grup", "tur", "secenekler", "sira", "aktif"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs["class"] = "form-check-input" if isinstance(f.widget, forms.CheckboxInput) else (
                "form-select" if isinstance(f.widget, forms.Select) else "form-control")


class TeskilatFormu(forms.ModelForm):
    class Meta:
        model = TeskilatBirimi
        fields = ["ad", "tur", "ust", "bolum", "sira", "aktif"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["ust"].queryset = TeskilatBirimi.objects.exclude(pk=self.instance.pk)
        self.fields["bolum"].required = False
        for f in self.fields.values():
            f.widget.attrs["class"] = "form-check-input" if isinstance(f.widget, forms.CheckboxInput) else (
                "form-select" if isinstance(f.widget, forms.Select) else "form-control")

    def clean_ust(self):
        ust = self.cleaned_data.get("ust")
        b = ust
        while b is not None and self.instance.pk:
            if b.pk == self.instance.pk:
                raise forms.ValidationError("Bir birim kendi altına taşınamaz.")
            b = b.ust
        return ust
