from django import forms

from .models import KimlikKaydi
from .okuma import tr_buyuk

ALANLAR = ["tur", "tc", "soyad", "ad", "dogum_tarihi", "cinsiyet", "seri_no", "uyruk", "son_gecerlilik",
           "anne_adi", "baba_adi", "veren_makam"]
BUYUK = ["soyad", "ad", "anne_adi", "baba_adi", "veren_makam", "seri_no", "uyruk"]


class KimlikFormu(forms.ModelForm):
    class Meta:
        model = KimlikKaydi
        fields = ALANLAR
        widgets = {
            "dogum_tarihi": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "son_gecerlilik": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, supheli=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tur"].choices = [("", "— seçilmedi —")] + KimlikKaydi.TURLER
        self.fields["cinsiyet"].choices = [("", "—")] + KimlikKaydi.CINSIYETLER
        self.fields["tc"].widget.attrs.update(inputmode="numeric", maxlength="11", autocomplete="off")
        for ad, f in self.fields.items():
            sinif = "form-select" if isinstance(f.widget, forms.Select) else "form-control"
            if ad in supheli:
                sinif += " border-warning bg-warning-subtle"
            f.widget.attrs["class"] = sinif

    def clean_tc(self):
        return "".join(c for c in self.cleaned_data.get("tc", "") if c.isdigit())

    def clean(self):
        veri = super().clean()
        for ad in BUYUK:
            if veri.get(ad):
                veri[ad] = " ".join(tr_buyuk(veri[ad]).split())
        return veri
