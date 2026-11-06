from django import forms
from django.utils import timezone

from .models import ProgramSurumu


class YuklemeForm(forms.Form):
    ad = forms.CharField(label="Sürüm adı", max_length=120, help_text="ör. 2026-2027 Güz – 3 Kasım değişikliği")
    dosya = forms.FileField(label="aSc XML dosyası", help_text="aSc → Veri Hazırla → aSc Timetables XML")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ad"].initial = f"Program {timezone.localdate():%d.%m.%Y}"
        self.fields["ad"].widget.attrs["class"] = "form-control"
        self.fields["dosya"].widget.attrs.update({"class": "form-control", "accept": ".xml"})

    def clean_dosya(self):
        f = self.cleaned_data["dosya"]
        if not f.name.lower().endswith(".xml"):
            raise forms.ValidationError("Lütfen .xml uzantılı aSc dosyasını seçin.")
        return f


class YayinForm(forms.ModelForm):
    class Meta:
        model = ProgramSurumu
        fields = ["baslangic", "bitis", "aciklama"]
        widgets = {
            "baslangic": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
            "bitis": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
            "aciklama": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["baslangic"].required = True
        self.fields["bitis"].help_text = "Boş bırakılırsa yeni bir sürüm yayınlanana kadar geçerlidir."

    def clean(self):
        veri = super().clean()
        if veri.get("baslangic") and veri.get("bitis") and veri["bitis"] < veri["baslangic"]:
            self.add_error("bitis", "Bitiş tarihi başlangıçtan önce olamaz.")
        return veri
