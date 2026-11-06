# Ders Programı modülü: KAMYOSİS uyumluluk istekleri

**Kime:** Ders Programı (`dersprogrami/timetable`) geliştiricisi ve onun Claude oturumu
**Kimden:** Mehmet / KAMYOSİS
**Tarih:** 02.11.2026

## Bağlam

`timetable` uygulaması KAMYOSİS'e (Django 5.2, Python 3.13, SQLite, waitress) **git subtree** ile alınacak. Siz
geliştirmeye devam ettikçe güncellemeleri biz çekeceğiz. Bu yüzden modülün koduna bizim tarafta yama yapmak
istemiyoruz. Aşağıdaki küçük değişiklikleri sizin tarafta yapmanızı rica ediyoruz.

KAMYOSİS'te modül `/ders-programi/` öneki altında çalışacak. Kullanıcı modeli KAMYOSİS'in `accounts.User` modeli
olacak (`AbstractUser` türevi). Giriş, parola ve yetki KAMYOSİS'ten yönetilecek. Ayrıntılı inceleme KAMYOSİS
deposundaki `docs/dersprogrami_entegrasyon_analizi.md` belgesinde. Satır numaraları o incelemenin yapıldığı
`claude/elegant-fermi-mtxjbt` dalına göre verildi.

## Temel ilke

**Bağımsız kurulum bugünkü gibi çalışmaya devam etmeli.** Her yeni davranış bir ayarla açılır. Ayarın varsayılan
değeri bugünkü davranışı korur. Mevcut testler değişmeden geçmeli; yeni ayarlar için ayrıca test eklenmeli.

KAMYOSİS'te açık kalacak özellikler: **ders programı hazırlama ve üretim, sınav programı, etkinlik/telafi/derslik
ayırma, girişsiz web yayını**. Kapalı kalacaklar: **nöbet, vekâlet, öğretmen hesapları, kullanıcı ve kurum
yönetimi, güncelleyici, yedekleme**. Nöbet ve vekâlet için KAMYOSİS'in kendi modülleri var.

---

## İstek listesi

Öncelik: **Z** = zorunlu (bu olmadan bağlayamayız), **Ö** = önemli, **İ** = isteğe bağlı.

### 1. Değiştirilebilir kullanıcı modeli (Z)

- Modellerdeki 19 `"auth.User"` başvurusu `settings.AUTH_USER_MODEL` olmalı. Yerler:
  - `models.py`: 255, 503, 511, 560, 588, 591, 613, 618, 771, 799, 1186, 1285, 1293, 1341, 1366, 1389, 1435, 1440
  - `exam_models.py`: 57
- Uygulama kodundaki 5 içe aktarma `get_user_model()` kullanmalı:
  - `accounts.py:7`
  - `notifications.py:7`
  - `request_views.py:6`
  - `teacher_accounts.py:19`
  - `forms.py:163`
- Testlerdeki `from django.contrib.auth.models import User` (64 dosya) `get_user_model()` olmalı.

**Kabul:**

- Migration'lar zaten `swappable_dependency` kullandığı için `manage.py makemigrations --check` değişiklik üretmemeli.
- Tercihen, `AUTH_USER_MODEL` özel bir modele çevrilmiş küçük bir test ayar dosyasıyla da testler geçmeli.

### 2. Rota kapatma ayarı (Z)

Yeni ayar: `TIMETABLE_DISABLED_ROUTES` (rota adı listesi, varsayılan boş).

- Listedeki rotalar `SchoolAccessMiddleware.process_view` içinde **süper kullanıcı dahil** herkese `Http404` döndürmeli.
- Menü (`templatetags/navigation.py` → `NAV_GROUPS`) bu rotalara giden öğeleri göstermemeli. Bunun için her menü
  öğesine rota adı eklenmesi yeterli; şu an URL'ler lambda içinde olduğu için dışarıdan süzülemiyor.
- Merkez paneli (`central.html`) ve diğer şablonlardaki bu rotalara giden bağlantılar da gizlenmeli.
  `{% url %}` kapalı bir rotayı çözemezse sayfa kırılmamalı.
- Kapatılan özelliklerin testleri, rota bu listedeyse atlanmalı (`skipIf`).

KAMYOSİS'te bu listeye konacak rotalar:

| Grup | Rotalar |
|---|---|
| Güncelleme ve yedek | `system_update`, `backups`, `backup_compare` |
| Yeni kurum açan | `create_demo`, `import_asc` (yeni kurum açan sürümü), `central_school_new`, `school_create` |
| Hesap ve yetki yönetimi | `institution_users`, `school_users`, `teacher_accounts`, `password_set*`, `password_forgot*` |
| Nöbet ve vekâlet | `duties`, `duties_print`, `substitutions` ve vekâletle ilgili diğer rotalar |

Rota adlarının tam listesini siz daha iyi bilirsiniz. Lütfen bu gruplara giren bütün rota adlarını, belgeye ya da
ayar örneğine yazın. İsterseniz grup bazında bayraklar da ekleyebilirsiniz (ör. `TIMETABLE_FEATURES = {"duty":
False, "substitution": False, "teacher_accounts": False}`). Biz yalnızca rota listesini kullanabiliriz.

**Kabul:** Listede bulunan `system_update`, `backups` ve `backup_compare` rotaları süper kullanıcıya 404 veriyor
(test). Menüde ve merkez panelinde bu öğeler görünmüyor.

### 3. Giriş, hesap ve çıkış bağlantıları ayarla (Z)

KAMYOSİS'in giriş ve parola sayfaları kullanılacak.

- `timetable:login` rotası `settings.LOGIN_URL` farklıysa oraya yönlendirmeli.
- `templates/timetable/base.html` içindeki şu bağlantılar ayardan okunmalı. Varsayılan değerler bugünkü rotalar olsun:

| Ayar | Bağlantı | KAMYOSİS'teki değer |
|---|---|---|
| `TIMETABLE_HOME_URL` | Marka ve logo bağlantısı | `core:panel` |
| `TIMETABLE_ACCOUNT_URL` | "Hesabım" | `parola_degistir` |
| `TIMETABLE_LOGOUT_URL` | "Çıkış" | `logout` |
| `TIMETABLE_BRAND_NAME` | Görünen ad | `KAMYOSİS · Ders Programı` |
| `TIMETABLE_BRAND_LOGO` | Logo, statik yol | `img/logo_beyaz.png` |

**Kabul:** Ayarlar verilmeden her şey bugünkü gibi. Ayarlar verilince bağlantılar o rotalara gidiyor.

Not: Bu yapılmazsa `base.html` dosyasını KAMYOSİS'te ezmek zorunda kalırız. O zaman sizin `base.html`
değişikliklerinizi her seferinde elle taşımamız gerekir.

### 4. Yayın sinyali (Z)

Bir program **yayınlandığında** KAMYOSİS'te otomatik olarak bir **taslak** sürüm oluşturacağız. KAMYOSİS'teki
asıl yayın (başlangıç tarihiyle) yine elle yapılacak.

- Yeni modül: `timetable/signals.py`

  ```python
  from django.dispatch import Signal
  timetable_published = Signal()     # gönderilen: school, timetable, user
  timetable_unpublished = Signal()   # gönderilen: school, user
  ```

- `views.py` içindeki yayınla ve yayından kaldır işlemlerinde (yaklaşık 349 ve 362. satırlar), `update(...)`
  çağrısından sonra şu şekilde gönderilmeli:

  ```python
  transaction.on_commit(lambda: timetable_published.send(
      sender=School, school=school, timetable=timetable, user=request.user))
  ```

- Yayın başka bir yerden de yapılıyorsa (API, toplu işlem, yönetim komutu) oralardan da gönderilmeli.
  Mümkünse yayın tek bir servis fonksiyonunda toplansın ve sinyal orada atılsın.
- Bir alıcı hata verirse TT'de yayın geri alınmamalı. Hata günlüğe yazılıp kullanıcıya uyarı olarak gösterilebilir.

**Kabul:** Bir alıcı bağlanan testte yayınla işleminden sonra alıcı doğru `school` ve `timetable` değerleriyle
çağrılıyor. Yayından kaldırınca ikinci sinyal geliyor.

### 5. Sınav için ek yetki kancası (Ö)

Sınav programını, ders programını düzenleme yetkisi olmayan bir sınav sorumlusu da hazırlayabilmeli. Yetkiyi
KAMYOSİS'in "Sınav Planları" birimine göre biz vereceğiz.

`access.py` içinde, yaklaşık 296. satırda, izinler hesaplandıktan sonra şu satır eklenmeli:

```python
perms = perms | set(getattr(request, "timetable_extra_perms", ()))
```

Bizim ara katmanımız sınav rotalarında `request.timetable_extra_perms = {"veri"}` yazacak.

**Kabul:** `timetable_extra_perms` ayarlanmış bir istek, üyeliğinde `veri` olmasa da sınav POST'unu yapabiliyor.
Ayarlanmamışsa davranış değişmiyor.

### 6. 403 yanıtı önek altında da JSON olmalı (Ö)

`access._deny` JSON mı HTML mi döneceğine `request.path.startswith("/api/")` ile karar veriyor (`access.py:223`).
`/ders-programi/api/...` altında bu koşul tutmuyor, düzenleyici hata mesajını gösteremiyor.

Düzeltme: `"/api/" in request.path` ya da `request.resolver_match.url_name.startswith("api_")`.

Aynı nedenle sabit yol kullanan 5 test dosyası (`"/program/"`, `"/giris/"`, `"/api/program/"`) `reverse()` kullanmalı.

### 7. Otomatik yedeği ve bağımsız komutları kapatabilme (Ö)

- `AUTO_BACKUP` zaten ayardan okunuyor (`services.py:108`). Varsayılanı `getattr(..., False)` olarak kalsın.
  KAMYOSİS bunu `False` yapacak.
- `management/commands/sunucu.py` dosyası `config.wsgi` içe aktarıyor. KAMYOSİS'te `config` başka bir proje.
  Komut yanlışlıkla çalıştırılırsa anlaşılır bir hatayla çıkması yeterli. Örneğin `TIMETABLE_STANDALONE = False`
  ise "bu komut bağımsız kurulum içindir" deyip dursun. `yedekle` komutu için de aynısı geçerli.

### 8. Uygulamanın kendi kendine yetmesi (Ö)

Subtree ile yalnızca `dersprogrami/timetable/` klasörünü alacağız.

- `timetable` içinden `config` ya da proje kökündeki başka bir modül içe aktarılmamalı (yukarıdaki `sunucu.py`
  dışında böyle bir yer bulmadık).
- Uygulamanın ihtiyaç duyduğu ayarlar, varsayılanlarıyla birlikte tek yerde belgelenmeli. Örneğin
  `timetable/README` içinde "Bağlayan projenin eklemesi gerekenler" başlığı altında şunlar yer almalı:
  - `INSTALLED_APPS`
  - middleware sırası
  - context processor ve `builtins`
  - `TIMETABLE_*` ayarları
  - `SOLVER_WORKERS`
  - `BACKUP_DIR`
  - `PUBLIC_URL`
- Statik dosyalar ve şablonlar uygulama klasörünün içinde olmalı. Şu an öyle görünüyor; değişmesin.

### 9. Bağımlılık listesi (Ö)

Uygulamanın gerektirdiği paketleri sabit sürümlerle yazın (`timetable/requirements.txt` ya da README içinde):
`ortools`, `protobuf`, `reportlab`, `segno`, `tzdata` ve gerekirse diğerleri.

KAMYOSİS Python 3.13, Windows 64 bit üzerinde çalışıyor.

### 10. aSc XML'de kalıcı kimlikler (İ)

`asc_xml.export_school` kimlikleri veritabanı numarasından üretiyor (`S{pk}`, `T{pk}`…). Program kopyalanınca
bunlar değişiyor. Kök öğedeki `idprefix:DP` seçeneği de kimliklere uygulanmıyor.

Bunu köprüde biz çözeceğiz (iş anahtarına çeviriyoruz). Ancak `export_school(..., stable_ids=True)` gibi bir
seçenek eklerseniz köprü sadeleşir. Bu seçenekte kimlikler şöyle olur:

- ders: `DP-D:<kısa kod>`
- sınıf: `DP-K:<kısa ad>`
- derslik: `DP-R:<ad>`
- öğretmen: `DP-O:<pk>`

**TC kimlik numarası hiçbir zaman XML'e yazılmamalı.**

---

## Bizim tarafta yapılacaklar (sizden bir şey gerekmiyor)

- Yetki eşitleme: KAMYOSİS yetkilerinden `Membership` kayıtları otomatik üretilecek. Tek `Institution` kullanılacak.
- Rota kapatma listesinin doldurulması, `/ders-programi/` bağlaması, `LoginRequiredMiddleware`.
- SQLite WAL ve zaman aşımı ayarları, `TIMETABLE_JOB_BACKEND="worker"` ile ayrı `calisan` süreci, çekirdek sınırı.
- Yayın sinyalini dinleyip programı KAMYOSİS'e taslak sürüm olarak aktaran köprü (`asc_xml` → KAMYOSİS içe
  aktarıcısı, öğretmenleri TC ile eşleme, A/B haftalı programları reddetme).

## Teslim

1. Değişiklikleri ayrı bir dalda yapıp ana dala birleştirin. Bize çekebileceğimiz bir **etiket** verin
   (ör. `kamyosis-uyum-1`).
2. Her istek için hangi ayarın eklendiğini ve kabul testinin adını kısa bir notla bildirin.
3. `manage.py test timetable --parallel 1` bağımsız kurulumda yeşil olmalı.

## Ayrıca: depo güvenliği (lütfen önce bu)

Depo şu an **herkese açık**. İçinde kök `db.sqlite3` ve sanal ortam klasörü de var. Veritabanında öğretmen adları ve
olası TC numaraları bulunabilir. Lütfen:

- depoyu **Private** yapın;
- `db.sqlite3`, `venv` ve benzeri dosyaları depodan çıkarıp `.gitignore`'a ekleyin;
- mümkünse git geçmişinden de temizleyin;
- Mehmet'in hesabına okuma yetkisi verin. Subtree ile çekebilmemiz için bu gerekiyor.

Biz o veritabanı dosyalarını açmadık ve kullanmayacağız.
