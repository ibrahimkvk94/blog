import io
import json

from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import Is


def komut(*args):
    import sys
    from unittest import mock

    tampon = io.BytesIO()
    with mock.patch.object(sys, "stdout", mock.Mock(buffer=tampon)):
        call_command("isler", *args)
    return json.loads(tampon.getvalue().decode("utf-8"))


class IsListesiTestleri(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sahip = User.objects.create_superuser("sahip", password="x-Parola-123")  # canlıdaki sahip de sistem yöneticisi
        cls.sahip.user_permissions.add(Permission.objects.get(codename="is_listesi", content_type__app_label="isler"))
        cls.admin = User.objects.create_superuser("yonetici", password="x-Parola-123")

    def test_yalniz_sahip_gorur(self):
        self.client.force_login(self.admin)  # süper kullanıcılık yetmez
        self.assertEqual(self.client.get(reverse("isler:liste")).status_code, 403)
        self.assertEqual(self.client.post(reverse("isler:liste"), {"islem": "ekle", "baslik": "x"}).status_code, 403)
        self.assertNotContains(self.client.get("/"), "İş listesi")
        self.client.force_login(self.sahip)
        self.assertEqual(self.client.get(reverse("isler:liste")).status_code, 200)
        self.assertContains(self.client.get("/"), "İş listesi")

    def test_akis_claude_onay(self):
        self.client.force_login(self.sahip)
        self.client.post(reverse("isler:liste"), {"islem": "ekle", "baslik": "Nöbet Excel çıktısı", "aciklama": "Aylık",
                                                  "oncelik": "acil"}, HTTP_HOST="kamyosis.ornek.ts.net")
        i = Is.objects.get()
        self.assertTrue(i.dis_erisim)
        veri = komut("liste")
        self.assertEqual([x["id"] for x in veri["ele_alinacak"]], [i.pk])
        self.assertTrue(veri["ele_alinacak"][0]["internetten_girildi"])
        # Claude riskli adımda onay ister
        komut("not", str(i.pk), "--durum", "onay", "--metin", "Hazır; canlıya almak için onay gerekiyor.")
        self.assertEqual(komut("liste")["ele_alinacak"], [])
        self.assertEqual(komut("liste")["bekleyen_onay"], 1)
        r = self.client.get("/")
        self.assertContains(r, "Onayınızı bekleyen iş")
        self.client.post(reverse("isler:liste"), {"islem": "onayla", "pk": i.pk})
        i.refresh_from_db()
        self.assertTrue(i.onaylandi)
        self.assertEqual([x["id"] for x in komut("liste")["ele_alinacak"]], [i.pk])
        komut("not", str(i.pk), "--durum", "yapiliyor", "--metin", "Canlıya alınıyor.")
        komut("not", str(i.pk), "--durum", "tamam", "--metin", "Canlıda.")
        i.refresh_from_db()
        self.assertEqual((i.durum, i.onaylandi), (Is.TAMAM, False))
        self.assertIsNotNone(i.tamamlanma)
        self.assertEqual([n["claude"] for n in komut("goster", str(i.pk))["notlar"]], [True, False, True, True])

    def test_soru_cevap(self):
        i = Is.objects.create(baslik="Rapor", olusturan=self.sahip)
        komut("not", str(i.pk), "--durum", "soru", "--metin", "Hangi ay?")
        self.client.force_login(self.sahip)
        self.assertContains(self.client.get("/"), "Claude&#x27;un sorusu var")
        self.client.post(reverse("isler:liste"), {"islem": "cevap", "pk": i.pk, "metin": "Ekim"})
        i.refresh_from_db()
        self.assertEqual(i.durum, Is.BEKLIYOR)
        self.assertEqual(komut("liste")["ele_alinacak"][0]["notlar"][-1]["metin"], "Ekim")
