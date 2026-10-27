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

## 2. Proje dosyalarını indir

**Kolay yol (ZIP):**
1. Tarayıcıda GitHub hesabına giriş yap ve şu adresi aç:
   https://github.com/ibrahimkvk94/blog/tree/claude/elegant-fermi-mtxjbt
2. Yeşil **Code** düğmesi → **Download ZIP**.
3. ZIP'i örneğin **Belgeler** klasörüne çıkar. İçinde `blog-...` adlı bir klasör oluşur.

**Git kullanıyorsan:**
```
git clone -b claude/elegant-fermi-mtxjbt https://github.com/ibrahimkvk94/blog.git
```

## 3. Proje klasörünü aç

Çıkardığın klasörün içindeki **`dersprogrami`** klasörüne gir. Kurulum dosyaları burada:
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

## Sık karşılaşılan sorunlar

| Sorun | Çözüm |
|---|---|
| “Python bulunamadı” | Python'u yeniden kur ve **“Add python.exe to PATH”** kutusunu işaretle. Sonra bilgisayarı yeniden başlat. |
| Paket yüklemesi hata veriyor | İnternet bağlantını kontrol et ve `kurulum.bat`'ı yeniden çalıştır. Python 3.12 ya da 3.13 kullandığından emin ol. |
| “Port 8000 kullanımda” | Program başka bir pencerede zaten açık; o pencereyi kapatıp yeniden dene. |
| Parolamı unuttum | `dersprogrami` klasöründe terminal aç ve şunları yaz:<br>Windows: `.venv\Scripts\activate` ardından `python manage.py changepassword KULLANICI_ADI`<br>macOS/Linux: `. .venv/bin/activate` ardından `python manage.py changepassword KULLANICI_ADI` |
| Yeni bir yönetici ekleme | Yukarıdaki gibi sanal ortamı etkinleştir ve `python manage.py createsuperuser` yaz. |

**Yedekleme:** Tüm veriler `dersprogrami` klasöründeki **`db.sqlite3`** dosyasındadır. Bu dosyayı kopyalamak yedek almak için yeterlidir.

**Windows'ta terminal açmak:** klasörü Dosya Gezgini'nde aç, üstteki adres çubuğuna tıkla, `cmd` yaz ve Enter'a bas.
