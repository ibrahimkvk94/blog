# Ders Programı

aSc TimeTables mantığıyla çalışan, Django tabanlı otomatik okul ders programı sistemi.
Tasarımın gerekçeleri için: [`../docs/asc-timetables-analizi.md`](../docs/asc-timetables-analizi.md).

## Kurulum

> Kendi bilgisayarına adım adım kurulum için: **[KURULUM.md](KURULUM.md)** (Windows'ta `kurulum.bat`
> ve `calistir.bat`, macOS/Linux'ta `kurulum.sh` ve `calistir.sh`).

Geliştirici kurulumu:

```bash
cd dersprogrami
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser              # giriş için (tüm sayfalar giriş ister)
python manage.py seed_demo                    # örnek lise: 4 şube, 15 öğretmen, 116 kart
python manage.py runserver
```

`http://localhost:8000/` adresinde giriş yapın. Tüm veri girişi uygulamanın kendi ekranlarından
yapılır (sol menü → Veri); yönetim paneli (`/admin/`) yalnızca ileri düzey işler için kalır.

### Kendi sunucunda yayına alma (Docker)

```bash
cd dersprogrami
docker build -t ders-programi .
docker run -d -p 8000:8000 -v ders-programi-veri:/data \
  -e DJANGO_SECRET_KEY="uzun-rastgele-bir-anahtar" \
  -e DJANGO_ALLOWED_HOSTS="okulum.example.com" \
  -e DJANGO_CSRF_TRUSTED_ORIGINS="https://okulum.example.com" \
  -e DJANGO_BEHIND_HTTPS_PROXY=1 \
  -e DJANGO_SUPERUSER_USERNAME=mudur -e DJANGO_SUPERUSER_PASSWORD="güçlü-bir-parola" \
  ders-programi
```

Veritabanı `/data` biriminde (SQLite) tutulur. Üretim işleri süreç içinde çalıştığı için imaj
gunicorn'u tek süreç ve 8 iş parçacığıyla başlatır; bunu artırmayın. Docker çalıştıran her
platformda (Render, Railway, Fly.io, kendi VPS'iniz) aynı imaj kullanılabilir; HTTPS'i platformun
ters vekili sağlar.

Komut satırından üretim: `python manage.py generate_timetable <okul_id> [--mode relaxed] [--time-limit 60]`

Ortam değişkenleri: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` (`1`/`0`), `DJANGO_ALLOWED_HOSTS`,
`TIMETABLE_SOLVER_TIME_LIMIT` (saniye, varsayılan 60), `TIMETABLE_RUN_IN_BACKGROUND` (`1`/`0`).

Testler: `python manage.py test timetable`

## Ekranlar

| Ekran | İçerik |
|---|---|
| **Veri girişi** | Okul ve ders saatleri (satır ekle/sil), ders adları, sınıflar (bölünme ve grup düzenleyici), öğretmenler (sınırlar), derslikler, binalar, kart ilişkileri. Öğretmen, sınıf, derslik ve ders adı formlarında tıklanarak düzenlenen müsaitlik ızgarası (uygun / yasak / koşullu) |
| **Dersler** | Sınıf ve öğretmene göre süzülen ders listesi, sınıf yükleri, ayrıntılı ders formu (birleşik sınıflar, gruplar, birden çok öğretmen/derslik, blok kartlar) |
| **Ders dağıtım çizelgesi** | Ders adı × sınıf matrisi: hücreye saat, blok ve öğretmen girme; öğretmen fırçasıyla tıklayarak/sürükleyerek toplu atama; bir dersin saatini görünen bütün sınıflara uygulama; seviye filtresi; canlı öğretmen ve sınıf yükleri; Excel'den “Öğretmen · Ders · Sınıflar · Saat · Blok” satırlarını yapıştırıp önizleyerek aktarma (yeni öğretmen ve ders adları otomatik eklenir) |
| **Çözülemeyen programın açıklaması** | Katı mod çözüm bulamazsa birlikte sağlanamayan en küçük kural kümesi (öğretmen sınırları, ders dağılımı, müsaitlikler, kart ilişkileri, kilitli kartlar) bulunur ve her kural düzeltileceği ekrana bağlanır |
| **Excel aktarımı** | Okul verisini beş sayfalı Excel olarak indirme (şablon olarak da kullanılır) ve geri yükleme; adlara göre ekleme/güncelleme, hatada hiçbir değişiklik kaydedilmez |
| **Sınıf ders tablosu** | Bir sınıfın tek öğretmenli derslerini tek tabloda saat, blok, öğretmen ve derslik seçerek girme; başka sınıftan saatleri kopyalama; toplam saat / kapasite göstergesi |
| **Genel bakış** | Okul özeti, veri denetimi, program sürümleri, yeni üretim (katı/gevşek mod, süre, başlangıç sürümü) |
| **Ana görünüm** | Satırlarda sınıflar / öğretmenler / derslikler, sütunlarda gün × saat. Başlık ve satır adları sabit, tüm ızgara yatay ve dikey kaydırılır. Satır arama; “Haftayı sığdır” (tüm hafta ekran genişliğinde) ve S/M/L yakınlaştırma; gizlenebilen sol menü ve tam ekran |
| **Program işlemleri** | Geri al / yinele (Ctrl+Z / Ctrl+Y); iki günü ya da iki ders saatini yer değiştirme; tümünü kilitle / kilitleri aç; kilitsiz kartları çıkarma; başka sürümle karşılaştırma (değişen kartlar vurgulanır ve listelenir); istatistik sayfası (öğretmen/sınıf boşlukları, günlük saatler, derslik doluluğu) |
| **Nöbet çizelgesi** | Nöbet yerleri ve günlük nöbetçi sayısı; öğretmenin derse geldiği ve dersi çok olan güne, eşit sayıda ve muafiyet/müsaitliğe uyarak otomatik dağıtım; elle düzeltme; yazdırma. Vekâlet önerisinde o gün nöbetçi olanlar önceliklidir |
| **Kart düzenleme** | Kart sürüklenir ya da tıklanıp hedef hücreye tıklanır. Seçili kart için her hücre renklenir: uygun / uyarılı / çakışmalı (çakışan kartlar bekleyenlere düşer) / uygun değil. Kilitleme, programdan çıkarma, "Bekleyenleri yerleştir" |
| **Üretim ekranı** | Arka planda çalışan üretimin canlı ilerlemesi (süre, bulunan çözüm, en iyi ceza) ve "Durdur ve en iyisini al" |
| **Doğrulama** | Programın sert/yumuşak kural ihlalleri; her düzenlemeden sonra güncellenir |
| **Vekâlet** | Tarihe göre devamsızlık girişi, her ders saati için sıralı vekil önerisi, kaydetme ve yazdırma |
| **Dışa aktarma** | Excel (sınıf/öğretmen/derslik genel görünümleri + kart listesi), aSc TimeTables XML, sınıf/öğretmen/derslik bazlı yazdırılabilir / PDF sayfalar (günler satırda ya da sütunda, ayrıntı/derslik seçimi, sınıf öğretmeni başlıkta) ve tek sayfalık özet çizelge |
| **İçe aktarma** | aSc TimeTables XML (2012 ve sonrası) dosyasından okul verisi ve yerleşmiş kartlar: sınıf kısa adları, sınıf öğretmeni, gruplar, gün kısıtları; kartlarda paylaşılan derslikler (spor salonu) otomatik algılanır |
| **Çok okullu yapı ve yetkiler** | Tek kurulumda birden çok okul. Merkez yönetici okul ekler ve okul yöneticisi atar. Okul kullanıcılarının okul bazında yetkileri vardır: görüntüleme, veri girişi, program, yayın, vekâlet, nöbet, kullanıcı yönetimi. Yetki devri yalnızca kendi yetkileri kadar yapılabilir. Erişim tek bir ara katmanda (`access.py`) URL adına göre denetlenir |
| **Versiyonlar** | Açılışta ve düzenleme sırasında otomatik, ayrıca notlu elle kayıt. Ön izleme, versiyona geri dönme (önce mevcut hal kaydedilir), versiyonu ayrı program olarak açma |
| **Raporlar** | Bireysel programlar (günler satır/sütun, sayfa başına 1/2/4), haftalık ve günlük çarşaf liste, öğretmen ders yükü, sınıf ders listesi, boş derslik ve boş öğretmen listesi, nöbet. Hücre içeriği, renk, yazı boyutu, sayfa yönü, başlık ve imza ayarlanabilir. Ayarlar şablon olarak kaydedilir, canlı ön izleme ve yazdırma |
| **Sağ tık menüleri** | Kart: kaldır, kilitle, bilgi, satırı temizle, derslik seç, dersi güncelle, hızlı değişiklik, bul, zaman tablosu, düzenle/müsaitlik. Satır başlığı: zaman tablosu, düzenle, dersleri, temizle/kilitle, yazdır. Boş hücre: oraya konabilecek bekleyen kartlar. Çakışmada sorulur: görmezden gel, çakışanları kaldır, yer değiştir, iptal |
| **Veri özellikleri (aSc)** | Kart dağılımı (2+2+1), sınıfsız ders (zümre toplantısı), ders adı / öğretmen varsayılan derslikleri, aynı anda birden çok derslik isteyen ders, aynı anda birden çok ders alan derslik, okul geneli kapalı saatler, öğretmen branşı ve hedef ders yükü, sınıf öğretmeni, bölünmeleri kopyalama, danışman uyarıları (grupların saat/uzunluk farkı, dersliksiz dersler, kapalı saatler) |

## Kavramlar

| Kavram | Anlamı |
|---|---|
| **Ders (Lesson)** | Ders adı + sınıf(lar)/grup(lar) + öğretmen(ler) + olası derslikler + haftalık saat + kart uzunluğu |
| **Kart (Card)** | Dersin tek oturumu. Haftada 6 saat ve uzunluk 2 olan bir ders 3 kart (blok ders) üretir |
| **Bölünme / Grup** | Sınıfı tamamen kapsayan gruplar (ör. Almanca/Fransızca). Aynı bölünmedeki gruplar aynı anda ders görebilir; farklı bölünmelerdekiler çakışır |
| **Birleşik ders** | Birden çok sınıfı/grubu olan ders (ör. 9-A ve 9-B'nin Almanca grupları birlikte) |
| **Müsaitlik** | Öğretmen/sınıf/derslik/ders adı/ders için gün×saat hücresi: yasak ya da koşullu (?) |
| **Kart ilişkisi** | Seçilen kartlara toplu kural (aSc kılavuzundaki gibi). Kümeler: günde en fazla N, farklı günler, aralarında en az N boş gün, en fazla / en az N güne yayılma. Zaman haritası (işaretli gün × saat hücreleri): günde en fazla N, ders olan en fazla N gün, haftada en fazla / en az N, “varsa en az N”. Günlük yapı: art arda en fazla N, günde en fazla N boşluk, boşluk en fazla N saat, en fazla N farklı başlangıç saati, aynı saate en fazla N gün. Eşzamanlılık: aynı anda olmasın, her saatte en fazla / en az N. Eşleşmeli: aynı anda, aynı gün, art arda (sıralı ya da sırasız). İki taraflı (A↔B): aynı gün olmasın, art arda olmasın, ertesi gün olmasın. Derslik: seçili dersliklerde haftada en fazla / en az N, en fazla N farklı derslik, günde en fazla N bina. Kart uzunluğu filtresi. “Uygula”: tüm seçime, her sınıf, öğretmen, sınıfta ders adı, öğretmenin sınıfı, grup ya da seviye için ayrı. Önem: kesin (sert) ya da yüksek/normal/düşük (ceza) |
| **Program (Timetable)** | Bir üretimin sonucu (sürüm). Yayınlanan sürüm vekâlet işlemlerinde esas alınır |
| **Hafta / dönem maskesi** | A/B haftası ya da dönemlik dersler. İki kart yalnızca ortak bir hafta-dönemde çakışabilir |

## Mimari

```
timetable/
  models.py            veri modeli
  solver/              Django'dan bağımsız çözücü katmanı
    problem.py         sade problem yapısı, öğrenci "atomları", kart ilişkisi tanımı
    builder.py         veritabanı → Problem
    feasibility.py     üretim öncesi veri denetimi (kesin imkânsızlıkları açıklayarak bildirir)
    cpsat.py           OR-Tools CP-SAT modeli (katı / gevşek mod, ilerleme, durdurma)
    validate.py        çözücüden bağımsız doğrulama (elle düzenlenmiş programlar için de)
  services.py          üretim, onarım ("bekleyenleri yerleştir"), doğrulama
  jobs.py              arka plan işleri (iş parçacığı; ilerleme ve durdurma bellekte)
  editing.py           kart için hücre uygunluğu, taşıma, programdan çıkarma
  grid.py              ana görünüm verisi
  substitutes.py       vekâlet önerileri
  asc_xml.py, excel.py içe/dışa aktarma
  views.py, urls.py    sayfalar ve JSON API
  templates/, static/  arayüz (harici bağımlılık yok)
```

**Öğrenci atomları:** Her sınıf, bölünmelerinin gruplarının kartezyen çarpımı kadar atoma ayrılır
(ör. {Kız, Erkek} × {Almanca, Fransızca} → 4 atom). Her grup bir atom kümesidir. İki ders ancak
atom kümeleri kesişiyorsa çakışır. Böylece bölünme kuralları tek ve genel bir kurala iner.

### Kısıtlar

Katı modda sert kısıtlar:
- her kart tam bir kez yerleşir; blok kartlar ardışık saatleri kaplar ve gün sonunu aşmaz
- öğretmen, öğrenci atomu ve derslik çakışmaz (ortak hafta-dönem içinde)
- yasak müsaitlik hücreleri kullanılmaz; derslik birden çok seçenekten birine atanır
- aynı dersin kartları günde en fazla N (varsayılan: mümkün olduğunca farklı günler)
- öğretmen: günde en fazla ders, günde/haftada en fazla boşluk, haftada en fazla gün, art arda en
  fazla ders, geldiği günlerde en az ders
- sınıf: günde en az / en fazla ders
- uzun teneffüs (ders saati ayarı) blok dersleri bölmez; derslik kapasitesi sınıf mevcuduna yetmeyen
  derslikler seçenekten çıkar
- önemi "kesin" olan kart ilişkileri; kilitli kartlar yerinde kalır

**Gevşek mod:** kaynak çakışmaları ve kilitli kartlar yine serttir; diğer sert kurallar ağır cezalı
kurala dönüşür ve sığmayan kartlar bekleyenlerde kalır. Böylece çözülemeyen veride bile en yakın
taslak ve kırılan kuralların listesi elde edilir.

Yumuşak kısıtlar (ceza puanı):

| Ağırlık | Kural |
|---|---|
| 10000 | yerleşmeyen kart (gevşek mod) |
| 1000 | gevşetilen sert kural (gevşek mod) |
| 300 / 60 / 15 | önemi yüksek / normal / düşük kart ilişkisi |
| 100 | sınıf (atom) programında boşluk |
| 50 | sınıfın güne ilk saatten başlamaması |
| 10 | öğretmen boşluğu |
| 5 | koşullu (?) hücre kullanımı |

## Bilinen sınırlar

- Arka plan üretimi aynı süreçte bir iş parçacığında çalışır; ilerleme ve durdurma bilgisi
  bellektedir. Birden çok uygulama süreciyle (ör. gunicorn çok işçili) çalışırken ilerleme ekranı
  başka süreçteki işi göremez; bu durumda Celery/RQ'ya geçilmelidir (`jobs.start`).

## Yol haritası

- [x] Veri modeli, admin ile veri girişi, üretim öncesi veri denetimi
- [x] CP-SAT ile üretim; kilitli kartlar, önceki sürümden ipucu
- [x] Arka planda üretim, canlı ilerleme, durdurma
- [x] Katı / gevşek mod, ceza dağılımı
- [x] Kart ilişkileri (günde en fazla N, farklı günler, art arda en fazla N, aynı anda), öğretmen gün sınırı
- [x] Ana görünüm (satır: sınıf/öğretmen/derslik, sütun: gün × saat), sürükle-bırak düzenleme, hücre uygunluk renklendirmesi, bekleyenleri yerleştirme
- [x] aSc XML içe/dışa aktarma, Excel, yazdırılabilir / PDF çıktılar
- [x] Vekâlet modülü
- [x] Veri giriş ekranları (okul ve saatler, ders adları, sınıflar ve bölünmeler, öğretmenler, derslikler, dersler, sınıf ders tablosu, kart ilişkileri, müsaitlik ızgarası)
- [x] Docker ile yayına alma
- [x] Ders bazında müsaitlik ızgarası
- [x] Excel ile toplu aktarım (ders adları, derslikler, sınıflar ve bölünmeler, öğretmenler, dersler)
- [x] Tek tıkla yerel kurulum ve çalıştırma betikleri
- [ ] Seminer (öğrenci seçimli) dersler ve öğrenci bazlı program
- [x] Çözülemezlik açıklaması (QuickXplain ile birlikte imkânsız en küçük kural kümesi)
- [x] Ders dağıtım çizelgesi: öğretmen fırçası, toplu saat, Excel'den yapıştırma
- [x] aSc'deki kart ilişkisi türlerinin çoğu (aynı gün, art arda, aynı anda olmasın, boş gün, gün sayısı, saat aralığı kuralları)
- [x] aSc kılavuzundaki eksikler: zaman haritası, iki taraflı ve derslik/bina ilişkileri, kart uzunluğu filtresi, grup/seviye bazlı uygulama, öğretmen art arda/en az ders, sınıf günlük sınırları, uzun teneffüs, derslik kapasitesi
- [ ] Çok süreçli dağıtım için Celery/RQ ile iş kuyruğu
