# KAMYOSİS

Kara Astsubay Meslek Yüksekokulu yönetim bilgi sistemi. Django 5.2 ile yazıldı. Veritabanı şimdilik SQLite (`db.sqlite3`).

## Depo ve Ders Programı modülü

KAMYOSİS, ortak depodaki (`ibrahimkvk94/blog`, dal `claude/elegant-fermi-mtxjbt`) `kamyosis/` klasörüdür. Ders
Programı modülü aynı depodaki `dersprogrami/` klasöründen kullanılır; ayrıntı: `docs/dersprogrami_modulu.md`.
Depoya veri girmez (veritabanı, yedekler, kayıtlar, parolalar ve aktarım dosyaları `.gitignore`'dadır).

## Çalıştırma

| Amaç | Nasıl |
|---|---|
| Geliştirme (sadece bu bilgisayar) | `gelistir.bat` → http://127.0.0.1:8000 |
| Kurum içi ağda yayın | `yayinla.bat` → ekranda yazan `http://<IP>:8000` adresi |

| Arka planda (penceresiz) başlat | `arkaplanda_baslat.bat` |
| Durdur | `durdur.bat` |
| Windows açılışında otomatik başlatmayı kapat | `otomatik_baslatmayi_kaldir.bat` |

Otomatik başlatma, Başlangıç klasöründeki `KAMYOSIS.lnk` kısayoluyla yapılır (Windows'a oturum açılınca penceresiz başlar). Sunucu çıktıları `kayitlar\sunucu.log` dosyasına yazılır.

Yönetim paneli: `/yonetim/` (sadece ana yönetici).

### Ağdan erişim için güvenlik duvarı (bir kez, yönetici olarak)

```powershell
New-NetFirewallRule -DisplayName "KAMYOSIS 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Domain,Private
```

### Giriş güvenliği ve internetten erişim (Tailscale Funnel)

- **İki adımlı doğrulama** isteğe bağlıdır: her kullanıcı sağ üst menü → “İki adımlı doğrulama”dan açar (Google /
  Microsoft Authenticator). Telefonunu kaybedenin kaydı Yönetim Paneli → İki adımlı doğrulama'dan silinir.
- **Hatalı giriş kilidi:** aynı kullanıcı adıyla 5 hatalı deneme (parola ya da kod) → 15 dakika kilit.
- **Güvenlik ayarları** (Yönetim Paneli): internetten girişte iki adımlı doğrulama zorunlu (varsayılan açık), deneme
  sınırı, kilit süresi. Kurum ağından giriş iki adımlı doğrulama zorunluluğundan etkilenmez.
- İnternet adresi depoya girmeyen `.dis_adres` dosyasına yazılır (ör. `https://ad.tailnet.ts.net`); bu adresten gelen
  formlar kabul edilir ve oradan gelen istekler “dış erişim” sayılır.

Funnel'ı açma / kapatma (site önce `yayinla.bat` ile çalışıyor olmalı):

```powershell
& "C:\Program Files\Tailscale\tailscale.exe" funnel --bg 8000        # aç: https://<makine>.<tailnet>.ts.net
& "C:\Program Files\Tailscale\tailscale.exe" funnel status           # durum
& "C:\Program Files\Tailscale\tailscale.exe" funnel --https=443 off  # kapat
```

## Access'ten veri aktarımı

```powershell
.venv\Scripts\python.exe manage.py access_aktar --deneme   # önce dene, hiçbir şey kaydetmez
.venv\Scripts\python.exe manage.py access_aktar            # Masaüstü\SinavMazeret_OrtakVeri.accdb
```

- Access dosyası önce geçici klasöre kopyalanır, asıl dosyaya dokunulmaz.
- Tekrar çalıştırılabilir; kayıtlar Access ID'sine göre güncellenir.
- Yeni kullanıcıların geçici parolaları `ilk_parolalar.txt` dosyasına yazılır. Kullanıcılar ilk girişte parolalarını değiştirmek zorundadır. Parolaları ilettikten sonra dosyayı silin.

## Organizasyon ağacı ve yetkiler

- **Yeni şube/kısım/görev:** Yönetim Paneli → Organizasyon ağacı → Ekle. Menü ve panel otomatik güncellenir.
- **Yetki:** Yönetim Paneli → Kullanıcılar → kullanıcı → Yetkiler.
  - Seviye: Görüntüleme / Düzenleme / Yönetim.
  - Kapsam: Tüm bölümler / Sadece kendi bölümü.
  - Bir birime verilen yetki tüm alt birimlerine geçer.

PPYS'den aktarılan varsayılan yetkiler:

| PPYS | KAMYOSİS |
|---|---|
| Ana yönetici | Süper kullanıcı (her şey) |
| Yönetici + PKS | Personel Bilgilerini Yönetme → Yönetim |
| Yönetici + DPS/DDS/DMS/BDD | Ders Planları → Yönetim |
| Yönetici + SMS/SPS/STS | Sınav Planları → Yönetim |
| Bölüm kullanıcısı | Personel → Görüntüleme, Plan Program → Düzenleme (kendi bölümü) |

## Ders Planları

- **aSc programı yükleme:** Ders Planları → Program sürümleri → XML yükle (veya `manage.py asc_aktar dosya.xml`). Her yükleme taslak gelir; başlangıç tarihi verilip yayınlanır. Aynı tarihi kapsayan sürümlerden en son yayınlanan geçerlidir.
- **Öğretmen eşleştirme:** aSc öğretmenleri personelle eşleştirilir; eşleşmeyenler yeni personel olarak eklenebilir.
- **Ders takibi:** tarihli dersler yayındaki programdan üretilir (tatiller hariç).
  - *Yapıldı:* tarihi geçen ders kendiliğinden yapılmış sayılır; beyan ve teyit yoktur. Ders sayıları "Yapılan ders raporu"ndan alınır.
  - *Devir:* geçmiş ya da gelecek derse açılabilir; talep (bölüm/düzenleme) → onay (Ders Planları yönetimi) → kesin (Plan Program yönetimi); iade/iptal; kararlar talep grubunun tamamına uygulanır. Hedef öğretmen o saatte doluysa talep açılmaz.
  - Geçmiş günlerin ve devir görmüş derslerin programı sonradan yayınlanan sürümle değiştirilemez.
- **Tatil günleri ve akademik dönem:** Yönetim Paneli → Takip.
- İş kurallarının PPYS'deki kaynağı: `docs/ppys_is_kurallari.md`.

## Mazeretler (Plan Program → Mazeretler)

- **Ders mazeretleri** (PPYS DMS karşılığı): personelin dönem boyunca her hafta geçerli gün × ders saati tablosu. ✗ ders verilemez, ? mümkünse verilmesin, boş = uygun.
  - Dönem Yönetim Paneli → Mazeretler → Ders mazeret dönemleri'nden açılır: bildirime açık/kapalı, son bildirim zamanı, bağlı Program Hazırlama programı, bölümlere not.
  - Bölüm hesapları (Plan Program'da "kendi bölümü" yetkisi) yalnızca kendi bölümlerinin personelini görür ve bildirir; dönem kapandıktan sonra yalnızca yönetim yetkisi değiştirebilir.
  - Mazereti olmayan personel için de bildirim yapılır ("Mazereti yok olarak kaydet" toplu düğmesi). Bildirimi eksik personel ana sayfada görünür.
  - Dönem bir programa bağlıysa her kayıt o programdaki öğretmenin müsaitliğine hemen yazılır (öğretmen ad soyadla eşleşir); "Program Hazırlama'ya aktar" tümünü yeniden yazar. Program Hazırlama'da öğretmen müsaitliğinde elle yapılan değişiklik, o personelin bir sonraki mazeret kaydında üzerine yazılır.
  - Aynı kişi aynı anda iki yerden düzenlerse ikinci kayıt reddedilir; her kaydın geçmişi tutulur.
- **Sınav mazeretleri** (PPYS SMS karşılığı): planlandı; aynı mantıkla sınav dönemindeki gün/oturumlar için.

## Klasör yapısı

```
config/     ayarlar ve adresler
accounts/   kullanıcı modeli, giriş, zorunlu parola değişikliği
core/       organizasyon ağacı, yetki sistemi, ana panel
personel/   personel, bölüm, rütbe/sınıf/unvan
program/    aSc içe aktarımı, program sürümleri, haftalık program
takip/      ders takibi: yapılan dersler, devir, yapılan ders raporu
mazeret/    ders (ve ileride sınav) mazeret bildirimleri
aktarim/    Access aktarım komutu
templates/  sayfa şablonları
static/     stil dosyası
```

## Testler

```powershell
.venv\Scripts\python.exe manage.py test
```

## Gizli dosyalar (paylaşmayın)

`db.sqlite3`, `.secret_key`, `ilk_parolalar.txt`, `test_hesaplari.txt`
