from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.validators import UnicodeUsernameValidator

from personel.models import Bolum, Personel, TeskilatBirimi


class _Secim(forms.ModelChoiceField):
    def __init__(self, qs, etiket, **kw):
        super().__init__(qs, required=False, label=etiket, empty_label="—", **kw)


class HesapFormu(forms.ModelForm):
    """Hesap bilgileri: ad, bağlı bölüm / teşkilat birimi / personel, durum."""

    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name", "bolum", "teskilat_birimi", "personel", "is_active", "parola_degismeli"]
        labels = {"first_name": "Ad / hesap adı", "last_name": "Soyad", "is_active": "Hesap açık",
                  "parola_degismeli": "Bir sonraki girişte parolasını değiştirsin"}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["bolum"] = _Secim(Bolum.objects.filter(aktif=True).order_by("ad"), "Bölüm")
        self.fields["teskilat_birimi"] = _Secim(
            TeskilatBirimi.objects.filter(aktif=True).exclude(tur=TeskilatBirimi.BOLUM).order_by("sira", "ad"),
            "Teşkilat birimi (şube müdürlüğü, kısım …)")
        bagli = get_user_model().objects.exclude(personel=None)
        if self.instance.pk:
            bagli = bagli.exclude(pk=self.instance.pk)
        self.fields["personel"] = _Secim(
            Personel.objects.filter(aktif=True).exclude(pk__in=bagli.values("personel_id"))
            .select_related("rutbe", "sinif", "unvan"), "Bağlı personel (kişisel hesap)")
        self.fields["personel"].label_from_instance = lambda p: p.tam_ad
        self.fields["teskilat_birimi"].help_text = "Doluysa hesap bölüm yerine bu birimi ve alt birimlerini görür."
        for ad, alan in self.fields.items():
            alan.widget.attrs.setdefault("class", "form-check-input" if isinstance(alan.widget, forms.CheckboxInput)
                                         else ("form-select" if isinstance(alan.widget, forms.Select) else "form-control"))


class YeniHesapFormu(HesapFormu):
    username = forms.CharField(label="Kullanıcı adı", max_length=150, validators=[UnicodeUsernameValidator()],
                               help_text="Harf, rakam ve @ . + - _ kullanılabilir. Büyük / küçük harf ayrılır.")
    parola = forms.CharField(label="Parola", max_length=128, widget=forms.TextInput(attrs={"autocomplete": "off"}))
    zayif_onay = forms.BooleanField(label="Parola zayıf olsa da kabul et", required=False)
    sablon = forms.ModelChoiceField(get_user_model().objects.none(), required=False, empty_label="— yetki verme —",
                                    label="Yetkileri şu hesaptan kopyala")

    class Meta(HesapFormu.Meta):
        fields = ["username", *HesapFormu.Meta.fields]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["sablon"].queryset = (get_user_model().objects.filter(is_superuser=False, is_active=True)
                                          .exclude(yetkiler=None).order_by("username"))
        self.fields["sablon"].widget.attrs["class"] = "form-select"
        self.fields["zayif_onay"].widget.attrs["class"] = "form-check-input"
        self.initial.setdefault("is_active", True)
        self.order_fields(["username", "first_name", "last_name", "bolum", "teskilat_birimi", "personel", "parola",
                           "zayif_onay", "parola_degismeli", "is_active", "sablon"])

    def clean_username(self):
        ad = self.cleaned_data["username"].strip()
        if get_user_model().objects.filter(username__iexact=ad).exists():
            raise forms.ValidationError("Bu kullanıcı adı (ya da büyük / küçük harf farkıyla aynısı) zaten var.")
        return ad

    def clean(self):
        veri = super().clean()
        parola = veri.get("parola")
        if parola and not veri.get("zayif_onay"):
            try:
                password_validation.validate_password(parola, get_user_model()(username=veri.get("username", "")))
            except forms.ValidationError as e:
                self.add_error("parola", list(e.messages) + ["Yine de bu parolayı kullanmak için aşağıdaki kutuyu işaretleyin."])
                self.zayif = True
        return veri


class ParolaFormu(forms.Form):
    parola = forms.CharField(label="Yeni parola", max_length=128, widget=forms.TextInput(attrs={"autocomplete": "off", "class": "form-control"}))
    zayif_onay = forms.BooleanField(label="Parola zayıf olsa da kabul et", required=False,
                                    widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))
    degistirsin = forms.BooleanField(label="İlk girişte kendi parolasını belirlesin", required=False, initial=True,
                                     widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))

    def __init__(self, *a, kullanici=None, **kw):
        super().__init__(*a, **kw)
        self.kullanici = kullanici
        self.zayif = False

    def clean(self):
        veri = super().clean()
        parola = veri.get("parola")
        if parola and not veri.get("zayif_onay"):
            try:
                password_validation.validate_password(parola, self.kullanici)
            except forms.ValidationError as e:
                self.zayif = True
                self.add_error("parola", list(e.messages) + ["Yine de bu parolayı kullanmak için kutuyu işaretleyin."])
        return veri
