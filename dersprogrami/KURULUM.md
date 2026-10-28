# Bilgisayara kurulum rehberi

Ders Programı'nı kendi bilgisayarında çalıştırmak için aşağıdaki adımları sırayla izle.
İlk kurulum yaklaşık 5 dakika sürer. Sonraki açılışlarda yalnızca 5. adım yeterlidir.

---

## 1. Python'u kur (bir kez)

1. https://www.python.org/downloads/ adresine git ve **Python 3.13**'ü indir.
2. Kurulumu başlat.
   - **Windows:** İlk ekrandaki **“Add python.exe to PATH”** kutusunu mutlaka işaretle, sonra **Install Now**.
   - **macOS:** İndirilen paketi aç ve adımları izle.
3. Kontrol et: bir terminal aç (aşağıdaki 3. adımda nasıl açılacağı yazıyor) ve şunu yaz:

   ```
   python --version
   ```
   macOS'ta: `python3 --version`. Ekranda `Python 3.13.x` görmelisin.

## 2. Proje dosyalarını indir (git ile — otomatik güncelleme için)

`calistir.bat` her açılışta GitHub'daki son sürümü kendiliğinden çeker. Bunun için proje **git ile** indirilmelidir.

1. **Git'i kur (bir kez):** https://git-scm.com/download/win adresinden indir ve kurulumu varsayılan ayarlarla tamamla.
   macOS'ta Terminal'e `git --version` yazman yeterli; yoksa kurulumu kendisi önerir.
2. **Terminal aç:** Windows'ta Başlat menüsüne `cmd` yaz ve Enter'a bas.
3. Şunları sırayla yaz:
   ```
   cd %USERPROFILE%\Documents
   git clone -b claude/elegant-fermi-mtxjbt https://github.com/ibrahimkvk94/blog.git
   ```
   macOS'ta ilk satır yerine `cd ~/Documents` yaz.
4. Depo gizliyse GitHub giriş penceresi açılır; bir kez giriş yap. Git bu girişi hatırlar ve sonraki güncellemelerde tekrar sormaz.

Proje **Belgeler\blog** klasörüne iner.

> **ZIP ile indirdiysen:** program çalışır ama kendini güncelleyemez; açılışta “Otomatik güncelleme kapalı” yazar.
> Güncellemeleri otomatik almak için yukarıdaki adımlarla bir kez git ile indir ve eski klasördeki
> `dersprogrami\db.sqlite3` dosyasını (verilerin) yeni klasördeki `dersprogrami` içine kopyala.

## 3. Proje klasörünü aç

**Belgeler\blog** klasörünün içindeki **`dersprogrami`** klasörüne gir. Kurulum dosyaları burada:
`kurulum.bat`, `calistir.bat`, `kurulum.sh`, `calistir.sh`.

## 4. Kurulumu çalıştır (bir kez)

**Windows:**
1. `dersprogrami` klasöründe **`kurulum.bat`** dosyasına çift tıkla.
2. Siyah pencere açılır ve paketler yüklenir (internet gerekir).
3. **“Örnek okul verisi yüklensin mi?”** sorusuna denemek için `E`, boş başlamak için `H` yaz ve Enter'a bas.
4. Yönetici hesabını oluştur. Kullanıcı adı ve e-posta (boş bırakılabilir) sorulur, sonra parolayı iki kez yazarsın.
   Parola yazarken ekranda görünmez; bu normaldir.
5. “Kurulum tamamlandı” yazısını görünce pencereyi kapat.

**macOS / Linux:**
1. **Terminal**'i aç ve `cd ` yazıp (sonunda bir boşluk bırak) `dersprogrami` klasörünü terminal penceresine sürükle, Enter'a bas.
2. Şunu yaz:
   ```
   sh kurulum.sh
   ```
3. Sorulara Windows'taki 3. ve 4. maddedeki gibi cevap ver.

## 5. Programı aç (her seferinde)

Açılışta sırayla şunlar olur: güncellemeler çekilir, yeni paketler ve veritabanı değişiklikleri uygulanır, program başlar.
İnternet yoksa güncelleme atlanır ve mevcut sürümle devam edilir.

**Windows:** `dersprogrami` klasöründe **`calistir.bat`** dosyasına çift tıkla.
**macOS / Linux:** Terminal'de `dersprogrami` klasöründeyken şunu yaz:
```
sh calistir.sh
```

Tarayıcı birkaç saniye içinde kendiliğinden **http://127.0.0.1:8000/** adresini açar. Açılmazsa bu adresi kendin yaz.
4. adımda oluşturduğun kullanıcı adı ve parolayla giriş yap.

**Kapatmak için:** siyah pencerede ya da terminalde `Ctrl + C`'ye bas veya pencereyi kapat.

---

## İlk kullanım

1. **Örnek okulla başladıysan:** okulu aç → **Yeni program üret** → **Üretimi başlat**. Sonra **Ana görünüm**'e geç.
2. **Kendi okulunu gireceksen:** Okullar → **Yeni okul**, sonra sol menüdeki **Veri** bölümünden sırayla doldur:
   1. **Okul ve saatler**
   2. **Ders adları**
   3. **Derslikler**
   4. **Sınıflar:** bölünme ve gruplar burada girilir.
   5. **Öğretmenler:** müsaitlik ızgarası burada.
   6. **Dersler:** en hızlısı her sınıf için **Ders tablosu**.

   Veriler Excel'deyse: **Veri → Excel aktarımı → Excel dosyasını indir**, dosyayı doldur ve aynı sayfadan yükle.

## Kurumlar, programlar ve kullanıcılar

- Kurumda (okulda) birden çok bağımsız **program** olabilir, ör. "2026/2027 MYO 1.YY", "2.YY", "Gece öğretimi". Her programın kendi saatleri, sınıfları, öğretmenleri, dersleri, sürümleri ve yayını vardır; hepsi aynı anda açık ve yayında olabilir. Sol menüdeki program seçicisiyle programlar arasında geçilir.
- **aSc'den aktarma:** Kurum sayfasında (sol menü → Kurumlarım → kurum adı) "aSc TimeTables'tan içe aktar": XML dosyası yeni program olarak ya da var olan bir programın yerine aktarılır. Yeni okul/kurum açılmaz.
- **Aynı öğretmenleri paylaşan programlar:** programın ayarlarında "Birlikte çalışan programlar" seçilirse, diğer programın yayındaki programında dolu olan öğretmen (ad soyada göre) ve derslik (ada göre) saatleri bu programda kapalı sayılır.
- Kurulumda (4. adım) oluşturduğun hesap **merkez yönetici**dir: tüm kurumları görür. **Merkez paneli**nden kurum ekleyip kurum yöneticisini atar.
- Kurum yöneticisi **Kurum kullanıcıları** sayfasından hesap açar; yalnızca kendi sahip olduğu yetkileri verebilir ve istenirse kullanıcıyı belirli programlarla sınırlar. Yetkiler: görüntüleme ve raporlar (herkeste), veri girişi, program üretme/düzenleme, yayınlama, vekâlet, nöbet, program ekleme ve aSc aktarma, kullanıcı yönetimi.

## Sık karşılaşılan sorunlar

| Sorun | Çözüm |
|---|---|
| “Python bulunamadı” | Python'u yeniden kur ve **“Add python.exe to PATH”** kutusunu işaretle. Sonra bilgisayarı yeniden başlat. |
| Paket yüklemesi hata veriyor | İnternet bağlantını kontrol et ve `kurulum.bat`'ı yeniden çalıştır. Python 3.12 ya da 3.13 kullandığından emin ol. |
| “Güncelleme alınamadı” | İnternet bağlantısını kontrol et. Proje dosyalarında elle değişiklik yaptıysan git güncellemeyi durdurur; değişikliği geri alıp yeniden aç. Verilerin (`db.sqlite3`) bundan etkilenmez. |
| “Port 8000 kullanımda” | Program başka bir pencerede zaten açık; o pencereyi kapatıp yeniden dene. |
| Parolamı unuttum | `dersprogrami` klasöründe terminal aç ve şunları yaz:<br>Windows: `.venv\Scripts\activate` ardından `python manage.py changepassword KULLANICI_ADI`<br>macOS/Linux: `. .venv/bin/activate` ardından `python manage.py changepassword KULLANICI_ADI` |
| Yeni bir yönetici ekleme | Yukarıdaki gibi sanal ortamı etkinleştir ve `python manage.py createsuperuser` yaz. |

**Yedekleme:** Tüm veriler `dersprogrami` klasöründeki **`db.sqlite3`** dosyasındadır (yanındaki `db.sqlite3-wal` ve `db.sqlite3-shm` de ona aittir). Dosya kopyalayarak yedek alacaksan önce programı kapat; açıkken yedek için Merkez paneli → Yedekler ekranını ya da `python manage.py yedekle` komutunu kullan.

**Windows'ta terminal açmak:** klasörü Dosya Gezgini'nde aç, üstteki adres çubuğuna tıkla, `cmd` yaz ve Enter'a bas.

## Kapalı ağ (internetsiz) kurulum — tüm ağın kullanımı için

İnternete çıkamayan bir ağda program, bir **sunucu bilgisayarda** çalışır; ağdaki herkes tarayıcıdan bağlanır.
Python ve tüm paketler pakete gömülüdür, hedef bilgisayara ayrıca bir şey kurulmaz (Windows 10/11 64 bit).

**1. Paketi hazırla (internetli bir Windows bilgisayarda):**

- *Kolay yol:* GitHub'da **Actions → “Kapalı ağ paketi”** sayfasında son başarılı çalıştırmayı aç, **Artifacts** bölümünden `DersProgrami-paket` dosyasını indir. İçinden `DersProgrami-YYYYMMDD.zip` çıkar. Paket her güncellemede gerçek bir Windows makinesinde kurulup sınanarak oluşturulur.
- *Kendin üretmek istersen:* proje klasöründe `paketle.bat`'a çift tıkla. Python kurulu olması gerekmez. Sonuç `dist\DersProgrami-YYYYMMDD.zip` dosyasıdır (yaklaşık 150–200 MB).

**2. Sunucu bilgisayara kur (kapalı ağda):**

1. Zip'i USB ile taşı ve sabit bir klasöre aç, ör. `C:\DersProgrami`.
2. `kurulum.bat`'a **sağ tıkla → Yönetici olarak çalıştır**. Gizli anahtar üretilir, veritabanı hazırlanır, yönetici hesabı sorulur ve güvenlik duvarında 8000 kapısı açılır.
3. `baslat.bat` ile aç. Pencerede `http://192.168.x.x:8000/` gibi bir adres yazar; ağdaki bilgisayarlar bu adresi kullanır.
4. Bilgisayar açılınca kendiliğinden başlasın istersen `otomatik_baslat.bat`'ı çalıştır (yönetici izni ister). Kaldırmak için `otomatik_baslat.bat kaldir` yaz.

**3. Güncelleme:** Yeni zip'i açmadan kurulum klasörüne kopyala ve `guncelle.bat`'a çift tıkla. Önce yedek alınır. Veritabanı (`db.sqlite3`), ayarlar (`.env`) ve `yedekler` klasörü korunur.

**Notlar:**

- Sunucu bilgisayara ağ yöneticisinden **sabit IP** iste; adres değişirse kullanıcılar bağlanamaz.
- Ayarlar `.env` dosyasındadır: `SUNUCU_PORT` kapı numarasıdır, `DJANGO_ALLOWED_HOSTS=*` ağdaki her adresten erişime izin verir.
- E-posta bildirimleri kapalı ağda çalışmaz. Ağda bir e-posta sunucusu varsa `.env`'e `EMAIL_HOST` vb. eklenebilir.
- Program açık kaldıkça 24 saatte bir kendiliğinden yedek alınır (`yedekler` klasörü). Geri yükleme ve başka bilgisayardan yedek yükleme: **Merkez paneli → Yedekler**. Bu klasörü düzenli olarak başka bir diske kopyala.
