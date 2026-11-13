# PPYS İş Kuralları — Access VBA analizi (KAMYOSİS'e taşıma için)

> **Kaynak:** Access ön yüzünden dışa aktarılan VBA, özellikle `MazeretKurulum.mod.bas` (~22.300 satır). Referanslar `FonksiyonAdı` (~satır N) biçimindedir; satır numaraları yaklaşıktır (± birkaç satır). `Form_*.bas` dosyaları birkaç satırlık olay yönlendiricileridir; zaman damgalı kopyalar geliştirici yedekleridir ve dikkate alınmamıştır.
> **Kapsam:** Yalnız iş kuralları, SQL mantığı, yetki ve eşzamanlılık. Form/kontrol oluşturma, renk, ikon ve yerleşim kodu atlanmıştır (dosyanın büyük bölümü bu tür koddur).
> **Gizlilik:** Kodda geçen kişi adları, sabit kullanıcı adları, parola tuzu/özeti değerleri bu belgeye alınmamıştır.
> **Belirsizlik:** Koddan kesin çıkarılamayan noktalar "**belirsiz**" veya "**açık soru**" olarak işaretlenmiştir.

## 0. Genel yapı ve ortak kavramlar

### 0.1 Modül kodları

`P141Kodlar` (~14270) ve menü rotaları `U161Rotalar` (~20210):

| Kod | Ad (kodda geçen) | Tablolar | Not |
|---|---|---|---|
| `PKS` | Personel / kimlik sistemi | `smPersonel`, `smBolum`, `smV47Secenek`, `smKullanici` | Ortak personel rehberi, bölüm ve hesap yönetimi |
| `SMS` | Sınav Mazeret Sistemi | `sm*` | Bkz. Bölüm 3.1 |
| `DMS` | Ders Mazeret Sistemi | `dm*` | Bkz. Bölüm 1.3 |
| `DPS` | Ders Planlama Sistemi | `dp*` | Bkz. Bölüm 1.2 |
| `DDS` | Ders programı ve değişiklikleri | `dd*` | Bkz. Bölüm 1.1 |
| `BDD` | Bölüm Ders Dozajı (branş) | `bd*` | Bkz. Bölüm 1.4 |
| `SPS` | Sınav Planlama Sistemi | `sp*` | Bkz. Bölüm 3.2 |
| `STS` | Skor Takip Sistemi | `st*` | Bkz. Bölüm 3.3 |
| `DZN` | Excel düzenleme aracı | — (veritabanına yazmaz) | Yalnız yöneticiler (`Y134Izin` ~12076 bölüm hesabına hep kapalı) |

### 0.2 İki ayrı "dönem" kavramı

- **Sınav dönemi** = `smDonem` (SMS/SPS/STS kullanır).
- **Öğretim dönemi** = `dmDonem` (`DersDonemID`, `OgretimYili` "2026-2027" biçimi, `DonemNo` 1/2, `IlkPazartesi`). DMS, DPS (`dpDers.DonemID`), BDD (`bdAtama.DonemID`) ve DDS (`ddDonem.DonemID` → `dmDonem.DersDonemID` FK) bu dönemi kullanır.

### 0.3 Hesap türleri (özet; ayrıntı Bölüm 2)

- **Bölüm hesabı**: `smKullanici.Yonetici=False`, `BolumID` dolu. Yalnız kendi bölümünün personeli/verisi.
- **Yönetici**: `Yonetici=True`. Tüm bölümlerde işlem yapar, ama yalnız `ppYoneticiModul`'de açık olan modüllerde.
- **Ana yönetici ("admin")**: `Yonetici=True AND AnaYonetici='ANA'` (benzersiz indeks → tek kişi). Tüm modüller + hesap/yetki yönetimi, DDS kesinleştirme, yedekten dönüş, bakım modu, DPS ders aktarımı, SMS kapsamı.

Kodda bu üç düzey sırasıyla `v4Admin=False`, `v4Admin=True`, `V49AnaYetki()`/`A143Ana()` ile ayrılır.

### 0.4 Sürüm katmanları

Uygulama ardışık "yamalar" ile büyütülmüş: her yama `PPYS1xxGuncelle` adlı bir kurulum yordamı, `CurrentDb.Properties("…Hazir")` bayrağı (ör. `DDS140Hazir`, `DDS142Hazir`, `PPYS143Hazir`) ve bazen tablo alanı ekler. İş kuralları bu bayraklara göre dallanır (ör. `D142Hazir()` ise blok görünümü). **Web'de yalnız en son katmanın davranışı alınmalıdır**; bu belge en güncel davranışı anlatır, eski dallara yalnız gerektiğinde değinir.

---

## 1. Ders Planları Modülleri

### 1.1 DDS — Ders programı, devir ve gerçekleşme (dd*)

Kod: `D140*` (~13191–14192), `D1401*` (~14192–14242), `D142*` (~14617–14760), `D143*` (~14765–15038), `D148*` (~15874–16020, Excel hazırlığı), `U158*`/`U171*`–`U174*` (~19539–22300, ÜYBS aktarımı). Kurulum `PPYS140Guncelle` (~14140), blok güncellemesi `PPYS142Guncelle` (~14705).

#### 1.1.1 Tablolar (`D140Sema` ~13217)

| Tablo | Alanlar | Anlam |
|---|---|---|
| `ddKilit` | `ID`=1, `Surum` | Tek satırlık global DDS yazma kilidi |
| `ddDonem` | `DonemID` (PK, FK→`dmDonem.DersDonemID`), `Baslangic`, `Bitis` | Öğretim döneminin ilk/son ders tarihi |
| `ddPlan` | `PlanID`, `DonemID`, `Ad`(150), `Baslangic`, `Bitis`, `Durum`(15) ∈ {`'Taslak'`,`'Yayin'`}, `Kaynak` (Excel dosya yolu), `Kullanici`, `Kayit` | Haftalık programın bir **sürümü**; tüm okul için tek program |
| `ddEsleme` | `EslemeID`, `KaynakAd`, `KaynakBolum`, `PersonelID` | Excel'deki ad+bölüm metninin PKS personeline kalıcı eşlemesi |
| `ddSlot` | `SlotID`, `PlanID`, `KaynakSatir`, `KaynakAd`, `KaynakBolum`, `PersonelID` (null=eşlenmedi), `Kod`, `Ders`, `Sinif`(30), `Kisim`(100), `Gun` BYTE, `Saat` BYTE, `Tur`(10), `Mekan`(150, metin) | Haftalık şablonun **1 ders saatlik (1 DS)** hücresi |
| `ddDers` | `DersID`, `PlanID`, `SlotID`, `PersonelID` (asıl), `BolumID` (asıl personelin yayın anındaki bölümü), `Tarih`, `Saat`, `Kod`, `Ders`, `Sinif`, `Kisim`, `Tur`, `Mekan`, `Beyan`, `BeyanZamani`, `Teyit`, `TeyitZamani` | Yayımlamada üretilen **tarihli** ders saati (1 satır = 1 DS) |
| `ddTalep` | `TalepID`, `DersID`, `YeniPersonel`, `YeniBolum`, `Durum`, `Gerekce`, `Isteyen`, `IstekZamani`, `Onaylayan`, `OnayZamani`, `Kesinleyen`, `KesinZamani`, `SonKarar`, `KararVeren`, `KararZamani`, `BlokGrup` (1.42'de eklendi) | Ders devri talepleri |
| `ddTatil` | PK(`DonemID`,`Tarih`), `Aciklama` | Ders işlenmeyen günler (tüm okul) |
| `ddGunluk` | `ID`, `Kayit`, `Kullanici`, `Islem`(50), `NesneID`, `Ayrinti` MEMO | Denetim günlüğü |

DDS tablolarında **satır bazlı `Surum` alanı yoktur**; eşzamanlılık `ddKilit` + durum koşullu güncellemelerle sağlanır (1.1.13).

#### 1.1.2 Yetki modeli (`D140Yetki` ~13256)

Her DDS işleminin başında (ve yazma işlemlerinde transaction içinde iki kez daha) çağrılır:
- Oturum DDS modülünde olmalı (`P7Yetki("DDS")` → `V43OturumGecerli`, Bölüm 2.4).
- `smKullanici` satırı oturumla birebir aynı olmalı: `Kullanici`, `ParolaSurum`, `Yonetici` bayrağı; bölüm hesabında ayrıca `BolumID`. Aksi halde `"Oturum veya yetki değişti."`.
- `yonetim=True` istenen işlemler: `Yonetici=True` (`"Yönetici yetkisi gerekli."`).
- `ana=True` istenen işlemler: `AnaYonetici='ANA'` (`"Yalnızca ana admin kesinleştirebilir veya kesinlesmeyi geri alabilir."`).
- Bölüm hesabı için ayrıca `ppModul` tablosunda `Kod='DDS' AND Acik=True` olmalı (`"DDS bölüm erisimi kapali."`).

| İşlem | Bölüm hesabı | Yönetici (DDS yetkili) | Ana yönetici |
|---|---|---|---|
| Programı görme / Excel raporu | Kendi bölümü (asıl veya devralan bölüm) | Tümü | Tümü |
| Devir talebi oluşturma | Yalnız asıl programı kendi bölümünde olan dersler | Tümü | Tümü |
| Talep onayı (`Onay`) / iade (`Iade`) | — | Evet | Evet |
| Kesinleştirme (`Kesin`) / geri alma (`Iptal`) | — | — | **Yalnız ana yönetici** |
| "Yapıldı" beyanı (`Beyan`) | Dersi **son durumda** veren personel kendi bölümündeyse | Tümü | Tümü |
| Fiili teyit (`Teyit`) | — | Evet | Evet |
| Dönem sınırı, tatil, Excel aktarımı, eşleştirme, T/U-mekan, yayımlama, ÜYBS | — | Evet | Evet |

Ekran düzeyinde (`U161RolGorur` ~20253) bölüm hesabı "Program aktarımı" (`DDS3`) ve "ÜYBS aktarımı" sayfalarını hiç görmez. DDS ekranı 4 sekmelidir (`D143Sayfa` ~14832): 0 Haftalık program, 1 Devir ve değişiklikler, 2 Gerçekleşen dersler, 3 Program yönetimi (yalnız yönetici).

Görünürlük filtresi `D140GorKosul` (~13355): bölüm hesabı `qDdSon` satırlarında `(BolumID=<bölüm> OR SonBolum=<bölüm>)` görür; talep listesinde `(d.BolumID=<bölüm> OR t.YeniBolum=<bölüm>)`. Devralacak personel listesi (`D140Kisiler` ~13392) bölüm hesabında varsayılan olarak kendi bölümü; "Tüm PKS personelini göster" (`tumPks`) işaretlenirse **tüm okul personeli** seçilebilir.

#### 1.1.3 Dönem sınırları ve tatiller

**Dönem sınırı** — `D140Donem` (~13453), yönetici:
- Tarihler `gg.aa.yyyy` (`D140Tarih` ~13234: tam 3 parça, 4 haneli yıl, geçerli takvim günü).
- `Bitis >= Baslangic` ve `DateDiff("d") <= 370` → `"Dönem aralığı 1-371 gün olmalı."`
- Dönemde mevcut planlardan biri yeni sınırların dışında kalıyorsa reddedilir (`"Mevcut program bu sinirlarin disinda kaliyor."`).
- `ddDonem` yoksa eklenir, varsa güncellenir. Günlük: `"Donem siniri"`.

**Tatil** — `D140Tatil` (~13479), yönetici:
- Tarih dönem sınırları içinde olmalı.
- Dönemde yayımlanmış plan varsa **geçmiş tarihe** tatil eklenemez (`dt < Date` → `"Yayımlanmış dönemin geçmiş tarihine sonradan tatil eklenemez."`).
- O tarihte `Talep`/`Onay`/`Kesin` durumunda devir varsa veya herhangi bir dersinde `Beyan`/`Teyit` varsa reddedilir.
- Tatil tüm bölümler için geçerlidir; açıklama zorunludur. Günlük: `"Tatil ekle"`.
- Tatil eklenince mevcut `ddDers` satırları **silinmez**; `qDdGuncel` ve `D140Aktif` tatil tarihini dışlar. Yayımlamadan önce girilen tatiller için hiç `ddDers` üretilmez. Ekran mesajı: tatilleri Excel yüklemeden önce girin.
- **Tatil silme/düzeltme işlevi yoktur** (kodda `DELETE FROM ddTatil` bulunmadı) → açık soru.

#### 1.1.4 Excel program aktarımı (`D140Aktar` ~13666, `D148Hazirla` ~15931)

Önkoşullar: yönetici; dönem seçili; formdaki tarih aralığı (`txtBas`–`txtSon`) **planın geçerlilik aralığı** olur ve `ddDonem` sınırları içinde, en çok 371 gün olmalıdır. Yalnız `.xlsx`; dosya salt-okunur, makrolar kapalı (`AutomationSecurity=3`) açılır; yalnız **ilk çalışma sayfası** okunur. Sınırlar: ≤20.000 satır, ≤150 sütun. Kimlik ve program hücrelerinde **formül yasaktır** (`D140Metin` ~13639: `HasFormula` → hata), Excel hata değerleri reddedilir. Herhangi bir hata **tüm aktarımı geri alır**. Tanı amaçlı adım günlüğü `%TEMP%\PPYS_DDS_Excel_<zaman>.log` dosyasına yazılır (`D1401Iz`; web'e taşınmaz). "Dosya yoluyla aktar" (`DDSExcelDosyadan` ~14210) yalnız dosya seçme penceresine alternatiftir.

**Biçim A — sabit şablon** (C1'de "ADI", E1'de "KOD" geçiyorsa doğrudan kullanılır):

| Sütun | İçerik | Zorunluluk |
|---|---|---|
| C | Öğretim elemanı adı soyadı (`KaynakAd`) | Satırın dolu sayılması için |
| D | Bölüm adı (`KaynakBolum`) | Satır doluysa zorunlu |
| E | Ders kodu (`Kod`) | Satırın dolu sayılması için |
| F | Ders adı (`Ders`) | Satırın dolu sayılması için |
| G | Öğrenci sınıfı (`Sinif`, metin) | Satır doluysa zorunlu |
| H… | Program hücreleri | — |

- **1. satır (H'den itibaren)**: gün adları. Birleştirilmiş hücre mantığı: boş başlık bir önceki günü devralır. Tanınan değerler (küçük harfe çevrilerek): `pazartesi`=1, `salı`=2, `çarşamba`=3, `perşembe`=4, `cuma`=5, `cumartesi`=6, `pazar`=7; başka metin → `"Taninmayan gün basligi"`. İlk program sütununda gün yoksa → `"Gün basligi eksik."`
- **2. satır**: ders saati numarası, **1–20 tam sayı**. Aynı gün+saat iki kez geçemez.
- 1. satırında `"Ders Saati"` veya `"Toplam"` geçen ilk sütun **toplam DS sütunudur**; program sütunları orada biter (toplam sütunu yoksa kullanılan aralığın sonuna kadar program sütunu sayılır).
- **Veri 3. satırdan** başlar; son satır C sütununa göre belirlenir.
- Satır kuralı: C, E, F üçü de doluysa ders satırıdır (D ve G zorunlu). Yalnız E veya F doluysa → `"Ders satirinda ad / kod / ders eksik"`. Diğer satırlar (yalnız ad, boş) atlanır.
- **Her dolu program hücresi = 1 haftalık DS** → bir `ddSlot`: `Gun`, `Saat` sütun başlığından; **hücre metni = `Kisim`** (şube/kısım etiketi); `Tur='Belirsiz'`, `Mekan=Null`, `KaynakSatir` = Excel satır no.
- Toplam sütunu doluysa sayı olmalı ve satırdaki dolu hücre sayısına **eşit** olmalı (`"Kaynak DS ile dolu saat hucreleri uyusmuyor"`). Toplam sütununda formül serbesttir.
- Hiç hücre yoksa aktarım reddedilir.
- Not (**doğrulanmalı**): gün eşleştirmesi VBA `LCase$` ile yapılıyor; büyük harfle yazılmış `SALI`/`ÇARŞAMBA` gibi başlıkların Türkçe küçük harfe doğru dönüşüp dönüşmediği Windows yerel ayarına bağlıdır. Biçim B'den gelen başlıklar `Salı`/`Çarşamba`/`Perşembe` olarak normalize edildiği için sorun yaşamaz.

**Biçim B — esnek başlıklı Excel** (`D148Hazirla`): Biçim A tanınmazsa,
- 1. satır başlıkları normalize edilir (`D148Baslik` ~15874: Türkçe harfler ASCII'ye katlanır, büyük harf, boşluk/`/`/`-`/`.`/`_`/satır sonu silinir) ve şu adlar aranır: `BOLUM|BOLUMADI` (zorunlu), `PERSONEL|ADISOYADI|ADSOYAD|ADISOYAD` (zorunlu), `DERS|DERSADI` (zorunlu), `KOD|DERSKODU` (isteğe bağlı), `SINIF|OGRENCISINIFI` (isteğe bağlı). Gün adı içeren **ilk** sütun program başlangıcıdır; 2. satır ders saati numaraları; `DS|TOPLAMDS|TOPLAMDERSSAATI` → "Toplam Ders Saati".
- Her dolu satır için ders **DPS'ten çözülür** (`D148Ders` ~15888): `dpDers.DonemID=<dönem>`, `smBolum.BolumAdi=<Bölüm>` (dersin **planlayan** bölümü), `dpDers.Ad=<Ders>` birebir, varsa `Kod`, varsa `Sinif` (yalnız `1`/`2`). Tam **bir** (Kod, Sınıf) çifti bulunmalı; yoksa `"…DPS eşleşmesi yok…"`, birden çoksa `"Birden fazla ders kodu veya sınıf eşleşiyor. Excel'e Ders Kodu ve Öğrenci Sınıfı sütunlarını ekleyip belirtin."`.
- Tüm hatalar toplanır; **tek bir eşleşmeyen satır bile tüm aktarımı durdurur**; liste `%LOCALAPPDATA%\Temp\DDS148_Eslesmeyen_<zaman>.txt` dosyasına yazılır.
- Başarılıysa Biçim A düzeninde yeni bir sayfa üretilir ve standart ayrıştırıcıya verilir.

**Kayıt**: tek transaction'da `ddPlan` (`Ad = "Program gg.aa.yyyy ss:dd"`, `Durum='Taslak'`, `Kaynak`=dosya yolu, `Kullanici`, `Kayit=Now`) + tüm `ddSlot` satırları. Günlük: `"Excel taslak"` (`"Satir=<n>; haftalik DS=<n>; <yol>"`). Ardından eşleştirme ekranı (`ddTaslak`) açılır.

#### 1.1.5 Personel eşleştirme (`D140EsleKisi` ~13648, `D140Esle` ~13808)

Aktarımda her satır için `PersonelID` şu sırayla bulunur:
1. `ddEsleme` içinde `KaynakAd=<ad> AND KaynakBolum=<bölüm>` **tek** kayıt → o personel.
2. Yoksa `smPersonel.AdSoyad=<ad>` **ve** `smBolum.BolumAdi=<bölüm>` olan **tek** personel.
3. Aksi halde `PersonelID=Null` (eşlenmemiş).

Karşılaştırma birebir metin eşitliğidir (Access metin karşılaştırması büyük/küçük harf duyarsızdır; boşluk/yazım farkı eşleşmeyi bozar).

Elle eşleştirme (yönetici, yalnız `Taslak` plan): seçilen satırın `KaynakAd+KaynakBolum` değerine sahip **plandaki tüm slotlara** aynı personel atanır; `ddEsleme`'deki eski kayıt silinip yenisi eklenir → **sonraki aktarımlarda otomatik eşlenir**. Seçilebilecek personel tüm okuldandır. Günlük: `"Personel esleme"` (`NesneID`=PlanID).

Not: Dersin bölümü (`ddDers.BolumID`) Excel'deki bölüm metninden değil, **yayın anındaki `smPersonel.BolumID`**'den alınır.

#### 1.1.6 Taslak düzenleme: tür ve mekan (`D140Esle(True)`)

- Yalnız `Taslak` planda, **tek slot** bazında (`"T/U ve mekan yalnızca seçili satira uygulanir."`).
- `Tur` ∈ {`T` (Teorik), `U` (Uygulama), `Belirsiz` (ekranda "Kaynakta yok")}. Excel'den gelen her slot `Belirsiz` başlar.
- `Mekan`: etkin `dpMekan` listesinden seçilir ama **ad metni** olarak saklanır (FK değil); boş → Null.
- Günlük: `"Taslak tur mekan"` (`NesneID`=SlotID).
- Yayımlanmış plan düzenlenemez (`"Yayımlanmış program duzenlenemez."`).

#### 1.1.7 Plan durumları ve yayımlama (`D140Yayin` ~13841)

Durum makinesi: **`Taslak` → `Yayin`**. Başka durum yoktur; **taslak silme, yayından kaldırma veya plan düzenleme işlevi yoktur** (kodda `DELETE FROM ddPlan` bulunmadı) → açık soru.

Yayımlama kuralları (yönetici, tek transaction):
1. Plan `Taslak` olmalı.
2. Dönemde zaten yayımlanmış plan varsa yeni planın `Baslangic` tarihi **bugünden önce olamaz** (`"Yeni surum geçmiş programi degistiremez. Ilk dönem aktarimi arsiv tarihlerini icerebilir."`). Yani yalnız **ilk** yayın geçmiş tarihleri (arşiv) içerebilir.
3. Yeni planın başlangıcı, dönemde yayımlanmış **tüm** planların başlangıcından **kesin olarak sonra** olmalı (`"Yeni surumun başlangıcı onceki yayinlardan sonra olmalı."`).
4. Eşlenmemiş slot olmamalı (`"Eslenmemis personeller var."`).
5. Aynı personelin aynı `Gun`+`Saat`'te iki slotu olmamalı (`"Personel programinda ayni gün / saat birden fazla ders var. Kaynagi duzeltin: personel ID …"`).
6. Plan aralığına düşen tarihlerde (dönemin **tüm** planlarındaki dersler için) `Talep`/`Onay`/`Kesin` devir olmamalı (`"Etkilenen tarihlerde devir kayıtları var. Talepleri iade edin; kesinleşmiş olanlari admin gerekceli geri alsin."`).
7. Aynı aralıkta `Beyan` veya `Teyit` içeren ders olmamalı (`"Fiili bildirimli program değiştirilemez."`).
8. **Tarihli ders üretimi**: her slot için `Baslangic..Bitis` arasındaki her gün dolaşılır; `Weekday(tarih, vbMonday) = Gun` ise ve tarih `ddTatil`'de değilse bir `ddDers` satırı eklenir (`PlanID, SlotID, PersonelID, BolumID=smPersonel.BolumID, Tarih, Saat, Kod, Ders, Sinif, Kisim, Tur, Mekan`). Hiç ders üretilmezse hata.
9. Onay mesajı `Tur='Belirsiz'` veya `Mekan Is Null` slot sayısını gösterir (**yayımlamayı engellemez**, yalnız uyarır) ve şunu vurgular: *"Bu aralikta eski program yerine tum okul icin bu surum kullanilacak. Excel tum personeli icermelidir."* → Plan **okul genelidir**; bölüm bazlı kısmi yükleme yoktur.
10. `UPDATE ddPlan SET Durum='Yayin' WHERE PlanID=… AND Durum='Taslak'` (1 satır etkilenmeli). Günlük: `"Program yayin"`.

#### 1.1.8 Geçerli ders kuralı — üst üste binen planlar (`D140Sorgular` ~13290, `D140Aktif` ~13310)

Eski planların `ddDers` satırları **silinmez**; hangi satırın geçerli olduğu sorguyla belirlenir:

```sql
-- qDdGuncel: bir tarihli ders, aynı dönemde DAHA GEÇ başlayan ve o tarihi kapsayan
-- başka bir yayımlanmış plan yoksa ve tarih tatil değilse geçerlidir.
SELECT d.*, p.DonemID
FROM ddDers AS d INNER JOIN ddPlan AS p ON d.PlanID = p.PlanID
WHERE p.Durum = 'Yayin'
  AND NOT EXISTS (SELECT * FROM ddPlan AS z
                  WHERE z.DonemID = p.DonemID AND z.Durum = 'Yayin'
                    AND z.Baslangic > p.Baslangic
                    AND d.Tarih BETWEEN z.Baslangic AND z.Bitis)
  AND NOT EXISTS (SELECT * FROM ddTatil AS h
                  WHERE h.DonemID = p.DonemID AND h.Tarih = d.Tarih);

-- qDdKesin: yalnız kesinleşmiş devirler
SELECT * FROM ddTalep WHERE Durum = 'Kesin';

-- qDdSon: geçerli dersin SON durumdaki personeli/bölümü
SELECT d.*,
       IIf(t.TalepID IS NULL, d.PersonelID, t.YeniPersonel) AS SonPersonel,
       IIf(t.TalepID IS NULL, d.BolumID,    t.YeniBolum)    AS SonBolum,
       t.TalepID AS KesinTalep
FROM qDdGuncel AS d LEFT JOIN qDdKesin AS t ON d.DersID = t.DersID;
```

Sonuçlar:
- Bir tarih için **en son başlayan ve o tarihi kapsayan** yayımlanmış plan geçerlidir ("latest published plan covering the date").
- Yeni planın `Bitis`'i eski planınkinden **önceyse**, yeni planın bitişinden sonraki tarihlerde **eski plan yeniden geçerli olur** (kodun doğal sonucu; kasıtlı mı → açık soru).
- Ders yükü/personel yalnız **kesinleşmiş** devirden sonra değişir (bekleyen veya reddedilen talepler orijinal dersi gizlemez — kodda açık yorum var).
- `D140Aktif(id)` her işlemde dersi yeniden doğrular: plan `Yayin` olmalı, tarih tatil olmamalı, daha yeni bir planla örtülmemiş olmalı (`"Ders yeni programla değişmiş; listeyi yenileyin."`).

#### 1.1.9 Blok görünümü (`D142Rows` ~14625, `D142Secim` ~14650)

- Liste satırları **ardışık ders saatlerinden oluşan bloklardır**. Anahtar (`D142Key`): `PlanID, PersonelID, Tarih, Kod, Ders, Sinif, Kisim, Tur, Mekan, Beyan, Teyit` + son personel; aynı anahtarlı ve `Saat` değeri bir öncekinin +1'i olan satırlar birleşir (`Saatler = "ilk-son"`, `DS = saat sayısı`).
- Devir ve fiili bildirim **seçili bloğun tüm saatlerine** uygulanır. "Saatleri ayrı göster" (`tekSaat`) ile tek saatlik (kısmi) işlem yapılabilir.
- `D142Secim`, seçimi transaction içinde yeniden kurar; blok değişmişse `"Blok değişmiş; programi yenileyin."`. Bölüm hesabı için her saatte asıl veya son bölümün kendi bölümü olması gerekir.
- Liste en çok ~29.000 karakter gösterir (Access ListBox sınırı; web'e taşınmaz). Excel raporu tüm kayıtları içerir.

#### 1.1.10 Devir talepleri (`ddTalep`) — durum makinesi

```
            (bölüm hesabı / yönetici)
                 D140Talep
                     │
                     ▼
               ┌──────────┐  Iade (yönetici)   ┌────────┐
               │  Talep   │───────────────────▶│  Iade  │ (son)
               └──────────┘                    └────────┘
                     │ Onay (yönetici)              ▲
                     ▼                              │ Iade (yönetici)
               ┌──────────┐─────────────────────────┘
               │   Onay   │
               └──────────┘
                     │ Kesin (YALNIZ ana yönetici)
                     ▼
               ┌──────────┐  Iptal (YALNIZ ana yönetici)  ┌────────┐
               │  Kesin   │─────────────────────────────▶│ Iptal  │ (son)
               └──────────┘                              └────────┘
```

Ekrandaki durum adları (`D142Talepler` ~14749): `Talep` → "Yönetici onayında", `Onay` → "Admin kesinleştirmesinde", `Kesin` → "Kesinleşti"; diğerleri ham değer.

**Talep oluşturma** — `D140Talep` (~13500):
- Ders bloğu ve devralacak personel seçilmeli; **gerekçe zorunlu**.
- Bölüm hesabı yalnız **asıl programı kendi bölümünde olan** (`ddDers.BolumID = kendi bölümü`) dersleri devredebilir (`"Yalnızca kendi personelinizin dersini devredebilirsiniz."`). Hedef personel başka bölümden olabilir.
- Kapsam:
  - Varsayılan: seçili bloktaki saatler (`D142Secim`).
  - "Seçili tarih aralığındaki haftalarda da devret" (`aralikDevir`): **aynı plan sürümünde**, aynı asıl personel, aynı `Kod`, `Kisim`, `Sinif`, `Tur`, `Mekan`, `Ders`, aynı **haftanın günü**, bloktaki saat numaraları ve formdaki tarih aralığındaki tüm dersler.
- Her ders için: `D140Aktif`; `Beyan`/`Teyit` varsa → `"Yapıldı bildirimi olan ders devredilemez."`; derste `Talep`/`Onay`/`Kesin` durumunda başka talep varsa → `"Ders için bekleyen veya kesinleşmiş devir var."` (yani bir ders aynı anda tek etkin devre sahip olabilir; `Iade`/`Iptal` sonrası yeniden talep edilebilir); `D140Uygun` (1.1.11).
- Ders başına bir `ddTalep(Durum='Talep', YeniPersonel, YeniBolum=<hedefin güncel bölümü>, Gerekce, Isteyen, IstekZamani=Now)` satırı.
- **`BlokGrup`**: aynı işlemde oluşturulan tüm taleplere ilk talebin `TalepID`'si yazılır. Talep listesi `Nz(BlokGrup, TalepID)` ile gruplanır (ilk/son tarih, DS adedi, saat aralığı). Eski (1.42 öncesi) talepler saat bazında kalır.
- Kaydetmeden önce sayfalı önizleme ve onay (`D140Onizle` ~13444). Önizleme metni: ders saati ve yer değişmez; tüm tarihler tek talep grubu olarak birlikte onaylanır; **DMS denetimi yalnız mevcut bildirim ve ilk 8 saat için yapılır, bildirimsiz veya 9+ saatleri yönetici ayrıca kontrol etmelidir.**
- Günlük: her ders için `"Devir talebi"` (`NesneID`=DersID, `"Hedef=<id> | <gerekçe>"`).

**Karar** — `D140Karar(islem)` (~13555):
- Her kararda **karar açıklaması zorunlu** (`SonKarar`), `KararVeren`, `KararZamani` yazılır.
- Karar, seçilen talebin **tüm `BlokGrup`'una** (tarih filtresinin dışındaki satırlar dahil) birlikte uygulanır; kullanıcıya DS sayısı gösterilip onay alınır.
- Gruptaki herhangi bir derste `Beyan`/`Teyit` varsa → `"Fiili ders bildirimi mevcut; devir karari değiştirilemez."`
- Geçişler:
  - `Onay`: önceki durum `Talep` olmalı; `D140Uygun` **yeniden** çalışır; `Onaylayan`, `OnayZamani`. (Yönetici)
  - `Kesin`: önceki durum `Onay` olmalı (`"Önce yönetici onayı gerekli."`); `D140Uygun` yeniden; `Kesinleyen`, `KesinZamani`. (Ana yönetici)
  - `Iade`: önceki durum `Talep` veya `Onay`. (Yönetici)
  - `Iptal`: önceki durum `Kesin` (`"Yalnızca kesinleşmiş devir geri alınır."`); **asıl personelin** o saatte hâlâ uygun olduğu doğrulanır (`D140Uygun(…, geri=True)`). (Ana yönetici)
- Güncelleme `… WHERE TalepID=… AND Durum=<önceki>`; 1 satır etkilenmezse `"Talep değişti; yenileyin."` (iyimser durum kontrolü).
- Günlük: `"Devir Onay"`, `"Devir Kesin"`, `"Devir Iade"`, `"Devir Iptal"` (`NesneID`=TalepID, `Ayrinti`=karar açıklaması).

#### 1.1.11 Uygunluk / çakışma denetimi (`D140Uygun` ~13330)

Talep, onay, kesinleştirme ve iptal öncesi çalışır:
1. Hedef personel `smPersonel`'de olmalı.
2. Hedef, dersin asıl personeli olamaz (`"Ders zaten bu personelin."`; iptalde atlanır).
3. **DMS mazereti**: dersin günü Pazartesi–Cuma (`Weekday(…,vbMonday) <= 5`) **ve** `Saat <= 8` ise hedefin `dmBildirim` kaydı (`DersDonemID = ddPlan.DonemID`) okunur. Kayıt varsa: maske uzunluğu 40 değilse `"DMS bildirimi geçersiz; önce duzeltin."`; `Mid(maske, (gün−1)×8 + saat, 1) = "1"` ise `"Seçilen personelin bu saatte DMS mazereti var."`. **Kayıt yoksa denetim yapılmaz.** Hafta sonu ve 9+ saatler denetlenmez.
4. **Aynı saat çakışması**: aynı `Tarih` ve aynı `Saat` numarasındaki diğer geçerli (yayımlanmış, tatil olmayan, daha yeni planla örtülmemiş) derslerin **son personeli** (`D140SonKisi`: kesin devir varsa yeni personel, yoksa asıl) hedefle aynıysa → `"Hedef personelin ayni tarih ve ders saatinde baska dersi var."`

Denetlenmeyenler: **bekleyen (`Talep`/`Onay`) devirler** (aynı kişiye aynı saate iki bekleyen talep oluşturulabilir; ikincisi en geç kesinleştirmede yakalanır), DPS ataması/yük sınırı, hedefin bölümü, mekan çakışması.

#### 1.1.12 Gerçekleşme: "Yapıldı" beyanı ve fiili teyit (`D140Fiili` ~13605)

| | `Beyan` ("Seçili ders yapıldı") | `Teyit` ("Yönetici fiili teyidi") |
|---|---|---|
| Kim | Herhangi bir DDS kullanıcısı; bölüm hesabı yalnız dersin **son personelinin güncel bölümü** (`smPersonel.BolumID`) kendi bölümüyse | Yönetici (DDS yetkili; ana yönetici şartı yok) |
| Ön şart | — | `Beyan` dolu olmalı (`"Önce yapıldı bildirimi gerekli."`) |
| Tarih | `Tarih <= Date` (gelecek tarihli ders beyan edilemez) | Aynı |
| Engeller | Zaten teyitli; zaten beyanlı; derste `Talep`/`Onay` bekleyen devir | Zaten teyitli; bekleyen devir |
| Yazılan | `Beyan = <oturum kullanıcı adı>`, `BeyanZamani=Now` | `Teyit = <oturum kullanıcı adı>`, `TeyitZamani=Now` |
| Günlük | `"Yapildi beyani"` (`"Personel=<son personel>"`) | `"Fiili teyit"` |

- İşlem seçili bloğun tüm saatlerine uygulanır (kısmi işlem için `tekSaat`).
- **Son tarih / zaman penceresi yoktur**: geçmişteki bir ders istenen zaman beyan/teyit edilebilir.
- **Geri alma yoktur**: kodda `Beyan`/`Teyit` alanını temizleyen veya beyanı reddeden bir işlem bulunmadı → açık soru.
- `Beyan`/`Teyit` bir dersi **dondurur**: o derse devir talebi açılamaz, grubundaki kararlar değiştirilemez, o tarihe tatil eklenemez, o tarihi kapsayan yeni plan yayımlanamaz.
- `Beyan` alanında personelin değil **hesabın** (çoğunlukla bölüm hesabı) kullanıcı adı tutulur.

#### 1.1.13 Kilit ve eşzamanlılık (`D140DB` ~13275, `D140Kilit` ~13280)

Her DDS yazma işlemi aynı kalıbı izler:
1. Ortak veri dosyasında ayrı bir DAO workspace açılır, `BeginTrans`.
2. `UPDATE ddKilit SET Surum=Surum+1 WHERE ID=1` → Jet satır kilidi commit'e kadar tutulur; **tüm DDS yazanları sıraya sokan global muteks** işlevi görür (1 satır etkilenmezse `"DDS kilit kaydi eksik."`).
3. `D140Yetki` transaction içinde yeniden çalışır (oturum/parola sürümü/yetki değişmişse işlem durur).
4. İş kuralları; durum koşullu güncellemeler (`WHERE Durum=<önceki>` + `RecordsAffected`), `D140Aktif`/`D142Secim` ile yeniden doğrulama.
5. Commit'ten hemen önce `D140Yetki` yeniden; hata halinde rollback.

`ddKilit.Surum` değeri başka hiçbir yerde okunmaz; yalnız kilit almak için artırılır.

#### 1.1.14 Denetim günlüğü (`ddGunluk`, `D140Iz` ~13286)

| `Islem` | `NesneID` | `Ayrinti` |
|---|---|---|
| `Donem siniri` | DonemID | `bas - son` |
| `Tatil ekle` | DonemID | tarih + açıklama |
| `Excel taslak` | PlanID | satır sayısı, haftalık DS, dosya yolu |
| `Personel esleme` | PlanID | `KaynakAd=… AND KaynakBolum=… -> <PersonelID>` |
| `Taslak tur mekan` | SlotID | `<tur> / <mekan>` |
| `Program yayin` | PlanID | yayın özeti |
| `Devir talebi` | DersID | `Hedef=<id> \| <gerekçe>` |
| `Devir Onay` / `Devir Kesin` / `Devir Iade` / `Devir Iptal` | TalepID | karar açıklaması |
| `Yapildi beyani` / `Fiili teyit` | DersID | `Personel=<id>` |

Günlüğü gösteren bir ekran yoktur; devir geçmişi Excel raporundaki "Devir kayıtları" sayfasında `ddTalep` alanlarından verilir.

#### 1.1.15 Raporlar (`D140Rapor` ~13927, `D142Excel` ~14687)

Kapsam: seçili dönem + tarih aralığı + görünürlük + (varsa) personel filtresi (`D143Filtre`: `SonPersonel=<id>`, raporda `SonPersonel` **veya** asıl `PersonelID`). Dosya `DDS_<zaman>.xlsx`, sayfalar:
- **Ders detayı**: Tarih, Hafta başlangıcı (Pazartesi), Ders saati, Kod, Ders, Sınıf, Kısım, Program personeli (asıl), Dersi verecek personel (son), T/U, Dershane/laboratuvar, DS (=1), Yapıldı beyanı (`Bekliyor`/`Beyan edildi`), Yönetici teyidi (`Bekliyor`/`Teyit edildi`), Program sürümü (PlanID).
- **Haftalık yük** (personel × hafta): `Program DS` (asıl personel), `Devredilen DS` (asıl ≠ son), `Devralinan DS`, `Kesin plan DS` (son personel), `Yapıldı beyan DS`, `Teyitli fiili DS`, `T DS`, `U DS`, `Türü belirsiz DS = Kesin plan − T − U`. Bölüm hesabında asıl tarafı yalnız `BolumID=kendi`, son tarafı yalnız `SonBolum=kendi` için sayılır.
- **Personel programı**, **Kısım programı** (sınıf/kısım bazında), **Devir kayıtları** (tüm `ddTalep` alanları), **Blok programı** (1.42).
- Sayfa başlığında not: haftalık toplamlar yalnız seçili aralıktaki dersleri içerir. Ad sütunlarının önüne `R151Kimlik` ile "Personel bölümü" ve "Sınıf / rütbe / unvan" eklenir.

#### 1.1.16 Silme korumaları (`D140SilmeKontrol` ~13207)

- `ddDonem` kaydı olan öğretim dönemi silinemez (`"Donemde DDS arsivi var; dönem silinemez."`).
- `ddSlot.PersonelID`, `ddTalep.YeniPersonel` veya `ddEsleme.PersonelID`'de geçen personel silinemez.

#### 1.1.17 ÜYBS aktarımı (`U158*` ~19539, `U171Aktar` ~21691, `U172*` ~21842, `U173Verify` ~22106, `U174Karsilastir` ~22215)

DDS menüsünde, yalnız yöneticiye açık ayrı bir araç. Amaç: üçüncü taraf ders programı çıktısından (Excel + aynı programın **aSc Timetables XML**'i) üniversite bilgi sistemine (ÜYBS) yüklenecek bir Excel üretmek ve sürümler arasında kalıcı satır referanslarını korumak. **`dd*` tablolarına yazmaz** (yalnız varsayılan dosya yolu için `ddPlan.Kaynak`'ı okur).

- **Girdi 1 — program Excel** (A:AS): B ders adı, C bölüm, D öğretmen adı, E isteğe bağlı `(U)` işareti, **F:AS = 40 hücre = 5 gün × 8 ders saati**; hücrede pozitif tam sayı **kısım numarası**. `"Kr.Tm.İşl."` ve `"Hazırlık 1"` hücreleri yok sayılır. Ders adında veya E'de `(U)` → uygulama.
- **Girdi 2 — "Kodlar" Excel**: `DERS` sayfası (A ad, B kod, C bölüm), `OGT` (A öğretmen adı, B kod), `BOLUM` (A önek, B değer). Aynı ad farklı koda bağlanamaz.
- **Girdi 3 — aSc XML**: Excel ile kısım/kod/gün/saat/öğretmen bazında **birebir** doğrulanır (`U173Verify`); en çok 2 öğretmen.
- **Çıktı satırı** (`U158Donustur`/`U158Yaz`): `KISIM NO`, `DERS KODU`, `GÜN` (0=Pzt…4=Cuma), `BAŞLANGIÇ`, `BİTİŞ`, `KSM`, `U / ORTAK` (1: uygulama veya aynı kısım/gün/saatte birden çok kaynak satırı), sabitler (I=1, J=1, L=11), `ÖĞRETİM ELEMANI 1/2`, P = PPYS iç referansı.
- **Ders saati saatleri** (`U158Saat` ~19556) — kodda sabit:

| Saat | Pzt–Per | Cuma |
|---|---|---|
| 1 | 08:20–09:00 | 08:20–09:00 |
| 2 | 09:10–09:50 | 09:10–09:50 |
| 3 | 10:00–10:40 | 10:00–10:40 |
| 4 | 10:50–11:30 | 10:50–11:30 |
| 5 | 11:40–12:20 | 11:40–12:20 |
| 6 | 12:30–13:10 | 14:10–14:50 |
| 7 | 14:10–14:50 | 15:00–15:40 |
| 8 | 15:00–15:40 | 15:50–16:30 |

- **Sürüm takibi**: `ppUybs172State` (tek satır: `Revision`, `BaseXml` = ilk hafta, `StateXml` = son onaylı durum, `ApprovedAt/By`, `DraftID`) ve `ppUybs172Draft` (`Status`: `BUILDING` → `READY` → `APPROVED`; `BlockCount`, `WarningCount`, `ChangeCount`).
- **Eşleştirme** (`U172Match`): aynı gün/saatte kalan saat eski referansını korur; taşınan saatler kronolojik sırayla eşlenir ("Eslesme_Onizleme" sayfası). Yeni ders, kaldırılmış ders, saat sayısı veya kısım değişikliği → **engelleyici kontrol kaydı** (taslak onaylanamaz).
- **"ÜYBS'ye işlendi" onayı** (`U172Islendi` ~22032): yönetici, ÜYBS'ye yüklemeyi bitirdikten sonra Taslak ID girer; `Status='READY'`, `BlockCount=0` ve `BaseRevision = güncel Revision` olmalı; `UPDATE … SET Revision=Revision+1 WHERE Revision=<rev>` ile iyimser onay. Yalnız rapor üretmek onaylı durumu değiştirmez.
- Çıktı sayfaları: `Degisenler`, `Ilk_Hafta`, `Guncel_Eslesenler`, `Degisim_Detayi`, `Kontrol`, `Eslesme_Onizleme`, `Aciklama`.
- `U174Karsilastir`: iki program Excel'ini hücre hücre karşılaştırıp değişenleri kırmızı işaretleyen yardımcı.

### 1.2 DPS — Ders Planlama (dp*)

#### 1.2.1 Tablolar (şema)

| Tablo | Alanlar | Anahtar / kısıt | Kaynak |
|---|---|---|---|
| `dpDers` | `DersID` COUNTER, `DonemID` LONG, `BolumID` LONG (**planlayan/veren bölüm**), `Sinif` LONG (1/2), `Kod` TEXT(50), `Ad` TEXT(150), `Kisim` LONG (dersin kapasitesi = alan bölümün o sınıftaki kısım sayısı), `Teorik` DOUBLE, `Uygulama` DOUBLE (kısım başına haftalık DS), `Surum` LONG, `AlanBolumID` LONG (sonradan eklendi; **dersi alan öğrenci bölümü**) | PK `DersID`; eski `uqDpDers(DonemID,BolumID,Sinif,Kod)` **kaldırıldı**, yerine `uqD14Ders(DonemID,BolumID,Sinif,Kod,AlanBolumID)`; FK `DonemID→dmDonem`, `BolumID→smBolum`, `fkD14Alan AlanBolumID→smBolum` | `DPSKur` ~8597, `D14Sema` ~9323 |
| `dpAtama` | `DersID`, `PersonelID`, `Tur` TEXT(1) (`'T'`/`'U'`), `Saat` DOUBLE (hesaplanan DS), `Kisim` LONG (personele verilen kısım sayısı; sonradan eklendi, eski kayıtlarda Null), `Mekan` TEXT(150) (dpMekan.Ad metni, FK değil) | PK `(DersID,PersonelID,Tur)`; FK ders/personel | `DPSKur` ~8598, `D12KisimAlan` ~8646, `P123MekanAlan` ~8659 |
| `dpGunluk` | `ID`, `DersID`, `PersonelID`, `Tur`, `Saat`, `Kullanici` TEXT(50), `Islem` TEXT(50), `KayitZamani` | FK `DersID` | ~8599 |
| `dpSinif` | `DonemID` PK, `Birinci`, `Ikinci`, `Surum` | **Eski (legacy)**: dönem geneli kısım sınırı. Kurulumda mevcut derslerden `Max(Kisim)` ile, en az 35 / 34 olacak şekilde doldurulur. Okuyan `D13Sinir` (~8800) artık hiçbir yerden çağrılmıyor → **ölü** | ~8600–8601 |
| `dpBolumKisim` | `DonemID`, `BolumID`, `Birinci` (1. sınıf kısım sayısı), `Ikinci` (2. sınıf), `Surum` | PK `(DonemID,BolumID)` | `D14Sema` ~9325 |
| `dpMekan` | `MekanID`, `Ad` TEXT(150) UNIQUE, `Aktif` YESNO, `Surum`, `BolumID` LONG (sonradan, Null olabilir) | `uqDpMekan(Ad)` | `D16Sema` ~9473, `M137Sema` ~12607 |
| `smBolum.MekanKodu` | TEXT(3), benzersiz (`uqM137Kod`, IgnoreNulls) | Mekan adı öneki | `M137Sema` ~12609 |

Kurulumda (`D16Sema` ~9475) `dpAtama.Mekan` içindeki farklı metinler `dpMekan`'a `Aktif=True` olarak taşınır. `M137Sema`, `MekanKodu` boş bölümlere, o bölümün tek bir 3 harfli `Yonetici=False` kullanıcı adını kod olarak atar (Access'e özgü göç adımı).

Kayıtlı Access sorguları (`D138Sorgular` ~12970) — DPS ekranının asıl veri modeli bunlardır:

```sql
-- qD138Ders : aynı dersin farklı alan bölüm satırlarını tek "grup" yapar
SELECT Min(DersID) AS GrupID, DonemID, BolumID, Sinif, Kod, Min(Ad) AS DersAdi, Teorik, Uygulama,
       Sum(Kisim) AS ToplamKisim, Count(*) AS AlanAdet
FROM dpDers GROUP BY DonemID, BolumID, Sinif, Kod, Teorik, Uygulama;
-- qD138Map : her dpDers satırını grubuna bağlar
SELECT D.DersID, G.GrupID FROM dpDers AS D INNER JOIN qD138Ders AS G
  ON D.DonemID=G.DonemID AND D.BolumID=G.BolumID AND D.Sinif=G.Sinif AND D.Kod=G.Kod
 AND D.Teorik=G.Teorik AND D.Uygulama=G.Uygulama;
-- qD138Atama
SELECT M.GrupID, A.* FROM qD138Map AS M INNER JOIN dpAtama AS A ON M.DersID=A.DersID;
-- qD138Yuk : grup başına atanmış kısım ve personel DS
SELECT GrupID, Sum(IIf(Tur='T',Nz(Kisim,0),0)) AS AnaKisim, Sum(IIf(Tur='U',Nz(Kisim,0),0)) AS EkKisim,
       Sum(Saat) AS PersonelDS FROM qD138Atama GROUP BY GrupID;
```

Not: Grup anahtarı `Teorik` ve `Uygulama`'yı da içerir; aynı kod farklı T/U ile girilirse **ayrı gruplar** oluşur. `GrupID=Min(DersID)` kararlı bir kimlik değildir (satır eklenip silinince değişebilir); ekran bunu `D138DersSec` içinde yeniden doğrular.

#### 1.2.2 Kavramlar ve sahiplik (çapraz bölüm dersleri)

- **Planlayan / veren bölüm** = `dpDers.BolumID`. Ders listesi (`D138ListeSql`) ve atamalar bu bölüm altında görünür/düzenlenir. Bölüm hesabı yalnızca `BolumID=v4Bolum` olan dersleri görür (`D11Bolum` ~8047).
- **Alan bölüm** = `dpDers.AlanBolumID` (öğrencilerin bölümü). Dersin `Kisim` değeri **alan bölümün** `dpBolumKisim` kaydından gelir: `Sinif=1 → Birinci`, `Sinif=2 → Ikinci` (`D14Kisim` ~9343). Kısım ayarı eksikse: `"Alan bölümün kısım ayarı eksik. Bölüm ID: …"`.
- Aynı ders birden çok alan bölüme verilirse her alan bölüm ayrı `dpDers` satırıdır; ekranda `qD138Ders` ile toplanıp **toplam kısım** olarak yönetilir (`"Aynı dersin alan bölüm kısımları toplanır. Personelin toplam kısım sayısını girin."`, `D138Form` ~13134).
- Veren bölümü değiştirme: yalnız yönetici, `Y134DersKaydet` (~12326): grubun **tüm** satırlarında `UPDATE dpDers SET BolumID=<yeni>,Surum=Surum+1 WHERE <grupKosul>`; etkilenen satır sayısı grup sayısına eşit olmalı; çakışmada (3022) `"Hedef bolumde ayni donem, sinif, ders kodu ve alan bolum kaydi zaten var. Kayitlar birlestirilmedi."`; günlük `Islem = "Veren bolum -> " & bid`. Atamalar korunur.
- Atanacak personel herhangi bir bölümden olabilir: `chkTumBolum` işaretliyse tüm `smPersonel` listelenir (`D11PersonelListe` ~8186). Yük, personelin kendi bölümüne değil **planlayan bölüme** raporlanır.

#### 1.2.3 Yetkiler

| İşlem | Kim | Referans |
|---|---|---|
| DPS ekranı, ders seçme, atama ekle/güncelle/kaldır, raporlar | DPS modül yetkisi olan oturum; bölüm hesabı yalnız kendi planlayan bölümü (`D11Auth`: `Yonetici=False AND BolumID=v4Bolum`), yönetici seçtiği bölüm (`Yonetici=True`) | `D11Auth` ~8058, `D11Bolum` ~8047 |
| Kısım ayarları (`dpBolumKisim`) | yönetici (`v4Admin`) | `D13AyarAc` ~8818, `D14Kaydet` ~9396 |
| Ders Excel şablonu ve ders aktarımı (dpDers oluşturma/güncelleme) | yalnız **ana yönetici** (`D11Master`: `Yonetici=True AND AnaYonetici='ANA'`) | `D11Master` ~8068, `D11Sablon` ~8250, `D11Aktar` ~8299 |
| Veren bölüm değiştirme | yönetici (+ `A143Izin("DPS")`) | `Y134DersKaydet` ~12326 |
| Mekan ekleme | yönetici veya kendi bölümü için bölüm hesabı (`M137Auth`: `Yonetici=True OR BolumID=bid`) | `M137Yaz(1)` ~12757 |
| Mekan etkin/pasif, silme, bölüm kodu, mekan Excel | yalnız yönetici (`P126Yetki`) | `M137Yaz(2/3)`, `M137KodYaz` ~12735, `M137Excel` ~12823 |
| Tüm bölümler toplu raporu | yönetici + `P7Yetki("DPS")` + `A143Izin("DPS")` | `R148Yetki` ~16021 |

**Ders silme ekranı yoktur.** `dpDers` yalnızca Excel'le eklenir/güncellenir ("Dosyada olmayan dersler silinmez"); silme yalnız `P126Plan` (~9063) dönem/personel temizliğinde olur.

#### 1.2.4 Görev türleri ve DS formülleri (çekirdek kural)

- `Tur='T'` = **"Ana gorev (T+U)"**: `Saat = Kisim × (Teorik + Uygulama)`
- `Tur='U'` = **"Ek uygulama"** (uygulamaya ek öğretim elemanı): `Saat = Kisim × Uygulama`. `Uygulama=0` ise tür listesinde `U` çıkmaz (`D138DersSec` ~13018) ve kaydetmede `"Bu ders icin uygulama saati yok."`.
- Ekran/rapor kırılımı: `TeorikDS = IIf(Tur='T', Kisim×Teorik, 0)`, `UygulamaDS = Kisim×Uygulama` (her iki türde), `ToplamDS = Saat`. Tutarlılık şartı `TeorikDS + UygulamaDS = Saat` (`R148Dps` ~16048 `Abs(t+u-ds) > 0.001` ise hata `"DPS T/U toplamı kayıtlı yükle uyuşmuyor. Personel ID: …"`).
- Bilgi metni: `"Ana görev: (T+U) x kısım. Ek uygulama: U x kısım."` (`D11Secim` ~8104) ve rapor kapsam sayfasında `"Ana görev DS=(T+U)*kısım; ek uygulama DS=U*kısım."`.
- DS değerleri **saklanır** (`dpAtama.Saat`) ve T/U veya kısım değişince yeniden yazılır:
  `UPDATE dpAtama SET Saat=Kisim*(T+U) WHERE DersID=… AND Tur='T'` ve `… SET Saat=Kisim*U … Tur='U'` (`D11Aktar` ~8399, `D14DersYenile` ~9385).

#### 1.2.5 Atama kaydetme — `D11Kaydet` → `D138Kaydet` (~satır 13044)

Girdi: seçili grup (`txtDers`=GrupID), `cmbPersonel`, `cmbTur` (`T`/`U`), `txtSaat` (etiketi **"Kısım sayısı"** — alan adı tarihsel olarak "Saat"), `txtMekan`.

1. Ders, personel, tür zorunlu: `"Ders, personel ve gorev turunu secin."`
2. Kısım: pozitif tam sayı (`D13TamSayi` ~8851, `"Kısım sayısı pozitif tam sayı olmalı."`).
3. Mekan: `"Birden fazla mekan - yeniden secin"` metni ile kayıt yapılamaz; mekan **zorunlu** ve `dpMekan` içinde `Aktif=True AND Ad=<mekan>` olmalı (`D16MekanKontrol` ~9511: `"Listeden etkin bir dershane/laboratuvar seçin. …"`). Silmede mekan kontrolü yok.
4. Transaction açılır; `D138Kilit` (~13013) dönemi kilitler; `D138Kosul` grup koşulunu kurar (`DonemID,BolumID,Sinif,Kod,Teorik,Uygulama`).
5. Ders seçili bölüm/döneme ait olmalı (`"Ders bu bolum/doneme ait degil."`).
6. **İyimser eşzamanlılık**: `D138Damga` = grup satırlarının `"DersID:Surum;"` birleşimi, ders seçildiğindeki değerle (`txtRev.Tag`) aynı olmalı; değilse `"Ders grubu veya atamalar degisti. Listeyi yenileyip dersi yeniden secin."`. Ardından `UPDATE dpDers SET Surum=Surum+1 WHERE <grup> AND <D11Auth>` (her atama değişikliği grubun tüm satırlarının sürümünü artırır).
7. Personel `smPersonel`'de olmalı.
8. Silmede, kişinin o türde ataması yoksa `"Kaldirilacak atama yok."`
9. **Yerine koyma semantiği**: kişinin grup içindeki o türdeki tüm atamaları `DELETE` edilir, sonra yeni toplam dağıtılır (silme = dağıtmadan çıkmak).
10. Grupta `Kisim Is Null` eski atama varsa engel: `"Grupta eski DS kayitlari var. …"`.
11. `tavan = Sum(dpDers.Kisim)` (grup), `birim = Uygulama (+ Teorik, Tur='T' ise)`.
12. Mevcut toplamlar + yeni kısım: `ana = Σ Kisim(T)`, `ek = Σ Kisim(U)`.
    - `ana > tavan` veya `ek > tavan` → `"Toplam kisim siniri asildi: <tavan>"`
    - `ek > ana` → `"Ek uygulama toplami ana gorev toplamindan fazla olamaz. Once ek uygulamayi azaltin."` (silmede de kontrol edilir; ana görev kaldırılırken ek uygulama fazla kalırsa engellenir.)
13. **Dağıtım**: grup satırları `DersID` sırasıyla dolaşılır; her satırda `bos = dpDers.Kisim − Σ(aynı türde mevcut Kisim)`; `bos<0` ise `"Mevcut atama alt kaydin kapasitesini asiyor. Yonetici kontrol etmeli."`; `pay = min(kalan, bos)`; `pay>0` ise
    `INSERT INTO dpAtama (DersID,PersonelID,Tur,Saat,Kisim,Mekan) VALUES (didx,pid,tur,pay*birim,pay,mekan)`.
    Her satır için `dpGunluk` kaydı (pay 0 olsa bile). Sonunda `kalan<>0` → `"Toplam kisim dagitilamadi. Islem geri alindi."`
14. Oturum yeniden doğrulanır, commit.

Sonuç: Personelin bir dersteki ataması tek mekan, tek toplam kısım olarak görünür; fiziksel olarak alan bölüm satırlarına bölünmüş birden çok `dpAtama` satırıdır.

#### 1.2.6 Kısım ayarları — `D14Kaydet` (~satır 9396) / form `dpSinifAyar`

- Bölüm + dönem başına `Birinci` ve `Ikinci`: 0 veya pozitif tam sayı (`D14Sayi` ~9378: `"Kısım sayısı sıfır veya pozitif tam sayı olmalı."`; form notu `"Sınıf yoksa 0 girin."`).
- `Surum=0` → `INSERT … SELECT … FROM smBolum WHERE BolumID=… AND <D11Auth>`; aksi halde `UPDATE … WHERE … AND Surum=<rev>`; 1 satır etkilenmezse `"Ayar veya yetki değişti; bölümü yeniden seçin."`.
- Aynı transaction'da `AlanBolumID=<bölüm>` olan o dönemdeki **tüm dersler** güncellenir: `dpDers.Kisim` yeni değere (sınıfa göre), `Surum+1`; `D14DersYenile`: eski Null kısımlı atama → engel; `Σ Kisim(T)` veya `Σ Kisim(U)` > yeni kısım → `"Kısım sayısı mevcut atamalardan küçük. Ders ID: …"`; `Uygulama=0` iken U ataması → engel; `Saat` yeniden hesaplanır; `dpGunluk.Islem='Bolum kisim ayari'`.
- Ekranda dönem toplamı: `D14Toplam` (~9351) → `"1. sınıf: ΣBirinci | 2. sınıf: ΣIkinci (ayarlı bölüm sayısı/toplam bölüm sayısı bölüm)"`.
- Not: `D11SayiKontrol` ders aktarımında `kisim < 1` ise `"Alan bolumun bu sinifinda kisim bulunmuyor."` verir; yani 0 kısımlı sınıfa Excel'den yeni ders girilemez, ama ayar sonradan 0'a çekilirse (atama yoksa) ders 0 kapasiteyle kalabilir.
- "D13 limitleri": DPS'te personel başına **azami haftalık yük sınırı bulunamadı**. "Sınır" kavramı yalnızca kısım kapasitesidir.

#### 1.2.7 Ders Excel şablonu ve içe aktarım

**Şablon** — `D11Sablon` (~8250), dosya `DPS_Ders_Sablonu_<yyyymmdd_hhnnss>_<salt>.xlsx`:
- Sayfa **`Dersler`**, başlıklar (A–I, tam metin): `BolumID`, `BolumAdi`, `Sinif`, `DersKodu`, `DersAdi`, `AlanBolumID`, `AlanBolumAdi`, `TeorikDS`, `UygulamaDS`. B ve G sütunlarında (2–1001. satırlar) `Bolumler` sayfasından açılır liste doğrulaması; A ve F sütunları formülle doldurulan ID'lerdir (`D16ExcelSecim` ~9478).
- Sayfa **`Bolumler`**: `BolumID`, `BolumAdi` (tüm `smBolum`). Adlandırılmış aralıklar `DPSBolumAdlari`, `DPSBolumKimlikleri`.
- Sayfa **`Donem`**: A1 `DonemID` / B1 dönem ID; A2 `Donem` / B2 dönem adı; A3 `Kısım sınırları` / `D14Toplam` metni; A4 `Kullanım`; A5 `Güncelleme` (açıklama metinleri: "DS, bir kısmın haftalık saatidir. Uygulama yoksa 0 yazın.", "Aynı dönem + veren bölüm + alan bölüm + sınıf + ders kodu güncellenir. Dosyada olmayan dersler silinmez. Ders kodu, sınıf veya bölüm değişirse yeni ders sayılır.").

**Aktarım** — `D11Aktar` (~8299), yalnız ana yönetici:
1. Dosya salt-okunur, makrolar kapalı açılır. `Donem!B1` formül olamaz ve seçili dönem ID'sine eşit olmalı (`"Şablon seçilen döneme ait değil."`). 9 başlık birebir aynı olmalı.
2. En çok 10.000 veri satırı. A ve F dışındaki hücrelerde Excel hatası/formül yasak. B..I (A/F hariç) tümü boş satır atlanır.
3. Satır doğrulamaları: `BolumAdi` ve `AlanBolumAdi` adla `smBolum`'da **tekil** bulunmalı (`D16BolumID` ~9501; aynı adlı iki bölüm → hata). A/F'deki ID'ler fiilen kullanılmaz (bölüm adla çözülür). `Sinif` tam sayı ve 1/2; `Kisim` = alan bölüm ayarından (dosyadan değil); `TeorikDS`,`UygulamaDS` sayı, ≥0, toplam >0 (`D11SayiKontrol` ~8080); `DersKodu` 1–50, `DersAdi` 1–150 karakter. Anahtar `BolumID|Sinif|Kod|AlanBolumID` dosyada tekrar edemez.
4. Transaction: `D138Kilit`; her satır için alan bölümün `dpBolumKisim` satırı `Surum+1` ile "dokunulur" (yoksa `"Alan bölümün kısım ayarı eksik veya yetki değişti."`).
5. Eşleşme: `(DonemID,BolumID,Sinif,Kod,AlanBolumID)` varsa güncelle. Yoksa ve aynı `(DonemID,BolumID,Sinif,Kod)` için `AlanBolumID Is Null` **eski** ders varsa: dosyada bu temel anahtar için tek satır olmalı, tek eski ders olmalı, kullanıcı onayı (`"…: Eski dersin TÜM mevcut atamaları <ID> ID'li alan bölüme bağlansın mı?"`) — eski kayıt bu alan bölüme bağlanır.
6. Yeni: `INSERT INTO dpDers (…,Surum,AlanBolumID) VALUES (…,1,alan)`. Güncelleme: `UPDATE dpDers SET AlanBolumID,Ad,Kisim,Teorik,Uygulama,Surum=Surum+1 WHERE DersID=… AND Surum=<rev> AND <D11Auth>`; ardından: Null kısımlı eski atama → engel; mevcut T veya U kısım toplamı > yeni kısım → `"Yeni kısım sayısı mevcut atamalardan küçük."`; `Uygulama=0` ve U ataması → `"Ek uygulama atamaları varken uygulama DS sıfırlanamaz."`; atama `Saat`'leri yeniden hesaplanır.
7. Her ders için `dpGunluk.Islem='Ders Excel'`. Herhangi bir hata tüm aktarımı geri alır (hata mesajına Excel satır no eklenir).

#### 1.2.8 DPS raporları ve Excel çıktıları

- **Ders listesi** (`D138ListeSql` ~12992): `GrupID`, `[Ders kodu / adi]`, `[Kapsam]` (= `AlanAdet & ' kayit birlesti'`), `[Sinif]`, `[Toplam kisim]`, `Teorik`, `Uygulama`, `[Ders DS] = ToplamKisim*(Teorik+Uygulama)`, `[Personel DS] = Nz(PersonelDS,0)`, `[Kalan kisim] = ToplamKisim − Nz(AnaKisim,0)`. Sıralama `Sinif, DersAdi, Kod, Teorik, Uygulama`.
- **Seçili dersin atamaları** (`D138DersSec` ~13018): personel+tür bazında `Kisim` toplamı, `Teorik DS`, `Uygulama DS`, `Toplam DS`, mekan (tek değilse `'Birden fazla mekan - yeniden secin'`), eski kayıt varsa `'Eski DS - kontrol'`.
- **Personel toplamları** (`D11RaporSql(True)` ~8158, form `dpOzet`): planlayan bölüm + dönem kapsamında personel başına `TeorikDS = Σ IIf(Tur='T',Kisim*Teorik,0)`, `UygulamaDS = Σ Kisim*Uygulama`, `ToplamDS = Σ Saat`; sütunlar `[Personel]`, `[PKS bölümü]`, `[Sicili]`, … Personelin başka bölümlerin planlarındaki yükü **dahil değildir**.
- **Eski kayıt kilidi** `D12EskiKontrol` (~8208): bölüm/dönemde `dpAtama.Kisim Is Null` varsa raporlar engellenir (`"Bu bölüm/dönemde eski DS kayıtları var. …"`).
- **Bölüm Excel raporu** `D11Excel` (~8426), dosya `DPS_Bolum_Plani_<ts>_<salt>.xlsx`, sayfalar:
  - `Ders Atamalari` (`D138RaporSql` ~13120): `Kod, Ad, Kapsam('Toplam'), Sinif, DersKisim, DersTuru ('Ana gorev (T+U)'/'Ek uygulama'), PersonelKisim, AdSoyad, Sicili, PersonelBolumu, TeorikDS, UygulamaDS, ToplamDS, DershaneLaboratuvar` (gruplu; ad sütunu önüne `"Personel bölümü"`, `"Sınıf / rütbe / unvan"` sütunları eklenir — `R151Kimlik`).
  - `Personel Toplamlari` (personel toplamları SQL'i).
  - `Ders Durumu` (`D138DurumSql` ~13130): `Kod, DersAdi, Sinif, ToplamKisim, Teorik, Uygulama, DersDS, AnaKisim, EkUygulamaKisim, KalanAnaKisim, PersonelDS`.
  - `Kapsam`: Bölüm, Dönem, Birim formül açıklaması, Oluşturma zamanı.
  - Tutarlılık: rapor öncesi ve sonrası `D11Damga` (bölüm+dönem `DersID:Surum` listesi) aynı olmalı, aksi halde `"Rapor hazirlanırken ders veya atama değişti. Yeniden rapor alın."`.
- **Tüm bölümler raporu** `R148Dps` (~16048) / `R148Excel` (~16133), dosya `DPS_Tum_Bolumler_<ts>_<salt>.xlsx`: Özet (planlayan bölüm başına `Teorik DS`, `Uygulama DS`, `Toplam DS`, `Görevli personel sayısı` — kişi bölüm içinde tekil, bölümler arasında tekrar edebilir), Ayrıntı (`Planlayan bölüm, Personel, Ders kodu, Ders, Sınıf, Görev, Atanan kısım, Teorik DS, Uygulama DS, Toplam DS, Derslik, Personel ID`), `Rapor bilgisi`. Her bölüm için `D12EskiKontrol` çalışır (bir bölümde eski kayıt varsa tüm rapor durur).

#### 1.2.9 Mekan (dershane/laboratuvar) — M137*

- Ad biçimi: `"<MekanKodu> - <ad>"` (`M137Ad` ~12658); kullanıcı kodu yazmışsa tekrar eklenmez; toplam ≤150 karakter; bölümün 3 harfli kodu yoksa ekleme yapılamaz (`"Bu bolumun 3 harfli kodunu yonetici … tanimlamali."`).
- `MekanKodu`: tam 3 harf; A–Z, a–z ve Türkçe `ÇçĞğİıÖöŞşÜü` (`M137KodUygun` ~12636); büyük harfe çevrilir; başka bölümde aynı kod olamaz (`M137KodYaz` ~12735). Kod değişince eski mekan adları değişmez.
- DPS'teki mekan listesi varsayılan olarak `dpMekan WHERE Aktif=True AND BolumID=<planlayan bölüm>`; `m137tum` işaretlenirse tüm etkin mekanlar (`M137DPSListe` ~12667). Seçilen atamanın mekanı bölüme ait değilse otomatik "tümü" açılır (`M137AtamaSec`).
- Etkin/pasif: `UPDATE dpMekan SET Aktif=Not Aktif,Surum=Surum+1 WHERE MekanID=… AND Surum=…`. Silme: yalnız `dpAtama.Mekan`'da (ad eşleşmesiyle) ve `spSalon`'da kullanılmıyorsa. Yeniden adlandırma yok. Benzersiz ad ihlali (3022): `"Bu mekan adi zaten kayitli."`.
- **Mekan Excel** (`M137Excel`): dışa `Mekanlar_<ts>_<oturum>.xlsx`, sayfa `Mekanlar` başlıkları `MekanID, BolumID, BolumAdi, MekanAdi, Aktif (1/0), Surum`; sayfa `Bolumler`: `BolumID, BolumAdi, MekanKodu`. İçe aktarımda: başlıklar birebir, ≤10.000 satır, formül/hata hücresi yok, `MekanAdi` zorunlu, `Aktif` `0`/`1`, `BolumAdi`→ID tekil ad, `BolumID` verilmişse eşleşmeli; mevcut ad → yalnız `Aktif` ve `BolumID` güncellenir (Surum kontrollü); yeni ad → bölüm zorunlu, ada kod öneki eklenir, dosyada verilen `MekanID` başka kayda aitse hata; dosyada tekrar eden ad → hata; dosyada olmayanlar silinmez.

#### 1.2.10 Kilitleme, sürüm ve günlük

- `Surum` alanları: `dpDers`, `dpBolumKisim`, `dpMekan` (+ `dmDonem`). Güncellemeler `WHERE … AND Surum=<okunan>` ve `RecordsAffected` kontrolü ile yapılır.
- `D138Kilit` (~13013): `UPDATE dmDonem SET DonemNo=DonemNo WHERE DersDonemID=… AND <D11Auth>` — dönem satırına yazma kilidi almak için sahte güncelleme (Access/DAO yöntemi); `Surum` artırılmaz, bu nedenle açık DMS ekranlarını etkilemez.
- `dpGunluk.Islem` değerleri: `'Ders Excel'`, `'Bolum kisim ayari'`, `'Toplam kisim kaydet: <n>'`, `'Toplam kisim kaldir: <n>'` (silmede `n=0`, `Saat=0` yazılır — silinen miktar günlüğe geçmez), `'Veren bolum -> <BolumID>'`. Atama kayıtlarında `PersonelID`, `Tur`, `Saat` (= o satıra düşen `pay*birim`) doldurulur. Günlüğü okuyan ekran/rapor **yoktur** (yalnız yazılır ve temizlikte silinir).
- Temizlik (`P126Plan` ~9063): dönem silinirse `dpGunluk, dpAtama, dpDers, dpSinif, dpBolumKisim, bdAtama, dmGunluk, dmBildirim, dmDonem`; personel silinirse ilgili `dpDers.Surum+1`, ardından `dmGunluk, dmBildirim, dpGunluk, dpAtama, bdAtama, spRol, smPersonel` silinir.

#### 1.2.11 DPS verisini kullanan diğer akışlar

- **D148\*** (~15874–16021, DDS Excel hazırlığı): esnek başlıklı ders programı Excel'i (başlıklar `D148Baslik` ile Türkçe harf katlanıp büyük harf, boşluk/`/-._` silinerek eşlenir: `BOLUM|BOLUMADI`, `PERSONEL|ADISOYADI|ADSOYAD|ADISOYAD`, `DERS|DERSADI`, `KOD|DERSKODU`, `SINIF|OGRENCISINIFI`, gün adları; 2. satır ders saati numaraları; veri 3. satırdan). Her satırda `dpDers` (seçili dönem, **planlayan** bölüm adı `smBolum.BolumAdi`, birebir `Ad`, varsa `Kod`, `Sinif` 1/2) ile **tek** `(Kod,Sinif)` bulunmalı; aksi halde `"Birden fazla ders kodu veya sınıf eşleşiyor. …"`. Tek eşleşmeyen satır bile tüm aktarımı durdurur; liste `%LOCALAPPDATA%\Temp\DDS148_Eslesmeyen_<ts>.txt`. Sınırlar: ≤150 sütun, ≤20.000 satır. C1'de "ADI" ve E1'de "KOD" geçen hazır şablon olduğu gibi geçirilir.
- **Z150\*** (~16348–16704, "DZN – Düzenleme"): yönetici + `A143Izin("DZN")`. "yy" haftalık program Excel'ini normalize eder, **veritabanına yazmaz**. Girdi: C, K, S, AA, AI sütunlarında `PAZARTESI…CUMA`, altındaki satırda her gün için `1..8`; başlık bloğu tekrarlanabilir; veri satırı A=personel adı, B=ders adı, C..AP (40 hücre) = kısım metni. Kısım hücresi başta rakam + isteğe bağlı harf (`"7ELN" → "7"`, 0 ve >6 hane hatalı, harften sonra rakam/simge hatalı — `Z150Kisim`); hatalı hücre aynen bırakılıp kontrol listesine yazılır. Eşleştirme: personel = `smPersonel.AdSoyad` normalize (`Z150Anahtar`: boşluk sadeleştirme, `i→İ`, `ı→I`, büyük harf) ve **tekil**; ders = personelin PKS bölümü (`= dpDers.BolumID`) + normalize ders adı → tek `Kod`. Çıktı `PPYS_Duzenleme_<ts>_<salt>.xlsx`: `Ders programı` (`Sıra, Bölüm, Sınıf / Rütbe / Unvan, Personel, Ders, Ders Kodu`, 40 gün×saat sütunu G..AT, `Toplam DS` = dolu hücre sayısı, `Personel Toplam DS` = aynı PersonelID'nin dosyadaki tüm satırları, `Kaynak satır`), `Kontrol listesi`, `Rapor bilgisi`.
- **U168/U170** (~21425–21475): DPS değil, ÜYBS ders programı aktarımının (U158/U171–U173) yardımcıları. Ders anahtarı = `"(U)"` ibaresi çıkarılmış normalize ders adı + bölüm (uzunluk önekli). `"(U)"` ders adında veya E sütununda geçerse uygulama sayılır. `DERS` eşleme sayfası: A ders adı, B kod, C bölüm; aynı ad+bölüm farklı koda bağlanamaz. Kaynak programda bir kısım/ders/gün/saat için en çok 2 öğretmen.
- **D140Uygun** (~13330, DDS): DMS maskesini okur (bkz. 1.3).
- **BDD**: personel DS toplamı `dpAtama.Saat` toplamından gelir (bkz. 1.4).

### 1.3 DMS — Ders Müsaitlik (dm*)

> Ekran adı "DMS - Ders Mazeret Sistemi". Kaydedilen bilgi personelin **haftalık mazeretli (müsait olmadığı) ders saatleri** şablonudur; dönem boyunca her hafta için geçerlidir ("Hafta sayısı belirtilmez").

#### 1.3.1 Tablolar (`PPYSKur` ~satır 4280–4282, ortak veri dosyasında)

| Tablo | Alanlar | Kısıt |
|---|---|---|
| `dmDonem` | `DersDonemID` COUNTER, `OgretimYili` TEXT(9), `DonemNo` BYTE, `IlkPazartesi` DATETIME, `GiriseAcik` YESNO, `SonBildirim` DATETIME (Null = sınırsız), `Surum` LONG (ilk kayıtta **0**) | `uqDmDonem(OgretimYili,DonemNo)` |
| `dmBildirim` | `DersBildirimID` COUNTER, `DersDonemID`, `PersonelID`, `SaatMaskesi` TEXT(40), `Aciklama` MEMO, `KayitZamani`, `Kaydeden` TEXT(50), `Surum` (ilk kayıtta **1**) | `uqDmBildirim(PersonelID,DersDonemID)`; FK personel, dönem |
| `dmGunluk` | `GunlukID`, `DersBildirimID`, `Kullanici`, `IslemZamani`, `Surum`, `SaatMaskesi` TEXT(40), `Aciklama` | `uqDmGunluk(DersBildirimID,Surum)` |

#### 1.3.2 `SaatMaskesi` kodlaması (kesin)

- Uzunluk **tam 40** karakter; yalnız `'0'` (AscW 48) ve `'1'` (AscW 49) (`P7MaskeGecerli` ~5079).
- Sıra **gün-öncelikli**: 5 gün (1=Pazartesi, 2=Salı, 3=Çarşamba, 4=Perşembe, 5=Cuma) × 8 ders saati (1..8). Konum (1 tabanlı): `pos = (gun − 1) × 8 + ders`. Yani 1–8 Pazartesi 1.–8. ders, 9–16 Salı, …, 33–40 Cuma (`P7MaskeOku` ~5089, `P7DersYukle` ~5111, `D140Uygun` ~13336).
- `'1'` = o saatte **mazeretli** (ders verilemez); `'0'` = müsait. Ekran notu: `"İşaretli ders mazeretlidir."`; Excel'de `"X"` = mazeretli.
- `String(40,"0")` kaydı anlamlıdır: **"mazereti yok" bildirildi**. Kayıt yokluğu = **bildirim eksik** (`"Mazereti olmayan personel için boş şablonu kaydedin."`).
- Hafta sonu ve 8'den sonraki saatler modellenmez (`D140Uygun` yalnız `gun<=5 And saat<=8` için kontrol eder).
- Okunan maske geçersizse ekran açılmaz: `"Kaydedilmiş haftalık şablon geçersiz. Yönetici kontrol etmeli."`.

#### 1.3.3 Giriş penceresi — `P7DersDonemiAcik` (~5098) ve `P7DersKayitKosulu` (~5179)

- Açık sayılması için: `dmDonem.Surum` = ekran açıldığında okunan sürüm **ve** `GiriseAcik=True` **ve** (`SonBildirim Is Null` **veya** `Now() <= SonBildirim`).
- Karşılaştırma **tarih+saat** (datetime) ile yapılır. `SonBildirim` = girilen tarih + saat (`ss:dd`, boşsa `"23:59"`) + **59 saniye** (`P7DonemKaydet` ~5297: `TimeSerial(h, m, 59)`). Saat girilip tarih boşsa hata.
- SQL tarafında aynı koşul: `T.GiriseAcik=True AND (T.SonBildirim Is Null OR T.SonBildirim>=Now())` ve `T.Surum=<okunan>`; kontrol hem açılışta, hem gün butonunda, hem kayıtta, hem commit'ten hemen önce tekrarlanır. Dönem kaydı (ör. giriş kapatma) `Surum`'u artırdığından açık tüm şablonlar geçersizleşir.
- Kapalıyken şablon salt-okunur açılır: `"Giriş süresi kapalı; yalnızca görüntülenebilir."`, düğme `"Kaydet / giriş kapalı"`.

#### 1.3.4 Kim kimin için giriş yapar

- Personel kendisi giriş yapmaz; giriş **hesaplar** üzerinden yapılır.
- Yönetici: herhangi bir bölümün personeli. Bölüm hesabı: yalnız `smPersonel.BolumID = v4Bolum` (`"Bu personel için yetkiniz yok."`).
- Kayıt SQL'inde yetki tekrar doğrulanır (`P7DersKayitKosulu`): `smKullanici` (Kullanici, `Yonetici` bayrağı oturumla aynı, `ParolaSurum`, bölüm hesabında `BolumID`), `smPersonel` (`PersonelID` ve seçilen `BolumID` — personelin bölümü değişmişse kayıt reddedilir), `dmDonem` açıklık koşulu.
- Dönem yönetimi (`dmDonemEkrani`) yalnız yönetici (`V4AdminKontrol`).

#### 1.3.5 Tekil giriş — `P7DersKaydet` (~5189)

- Seçim (personel/dönem/bölüm) şablon açıldığından beri değişmemiş olmalı (`"Seçim değişmiş. Haftalık şablonu yeniden açın."`).
- `Aciklama` trim edilir, ≤2000 karakter; boş → `Null` (`P7BosSql`).
- Yeni: `INSERT INTO dmBildirim (DersDonemID,PersonelID,SaatMaskesi,Aciklama,KayitZamani,Kaydeden,Surum) SELECT did,P.PersonelID,mask,acik,Now(),kullanici,1 FROM smPersonel AS P WHERE P.PersonelID=pid <kosul>`.
- Güncelleme: `UPDATE dmBildirim SET SaatMaskesi,Aciklama,KayitZamani=Now(),Kaydeden,Surum=Surum+1 WHERE DersBildirimID=… AND PersonelID=… AND DersDonemID=… AND Surum=<rev> <kosul>`.
- `RecordsAffected<>1` → `"Başka kullanıcı kaydı değiştirdi veya yetki/süre değişti. Şablonu yeniden açın."`.
- Her başarılı kayıtta `dmGunluk`'e **tam anlık görüntü**: `(DersBildirimID, Kullanici, IslemZamani=Now(), Surum=<yeni sürüm>, SaatMaskesi, Aciklama)`. Böylece her sürümün maskesi geri izlenebilir. Günlüğü okuyan ekran yoktur.
- Gün düğmesi `P7DersGunSec` (~5340): o günün 8 saatinin tümü seçiliyse temizler, değilse 8'ini de seçer (kaydetmez, yalnız formu değiştirir).

#### 1.3.6 Dönem yönetimi — `P7DonemKaydet` (~5297)

- `OgretimYili` `"####-####"` ve ardışık yıllar (`"Öğretim yılı 2026-2027 biçiminde olmalı."`, `"… ardışık iki yıldan oluşmalı."`).
- `DonemNo` ∈ {1,2}.
- `IlkPazartesi` `gg.aa.yyyy` (`P7Tarih` ~5244: tam 10 karakter, `##.##.####`, yıl 2000–2100, geçerli takvim günü) ve pazartesi olmalı.
- `GiriseAcik`, `SonBildirim` (bkz. 1.3.3).
- Yeni dönem `Surum=0`; güncelleme `Surum+1` ve `Surum=<rev>` kontrollü. **Bildirim alınmış dönemde** yıl, dönem no veya ilk pazartesi değiştirilemez (`AND NOT EXISTS (SELECT * FROM dmBildirim WHERE DersDonemID=…)`); giriş durumu ve son bildirim her zaman değiştirilebilir.

#### 1.3.7 Toplu giriş (`dmToplu`) — P8* (~6657–7072)

- Bölüm + dönem seçilir; dönem açık olmalı (`P8Yukle` ~6725). Bölüm hesabı yalnız kendi bölümü.
- Bölümün **tüm** personeli (`smPersonel WHERE BolumID=…`, sıralama `AdSoyad,PersonelID`) geçici yerel bir Access dosyasındaki `Taslak` tablosuna (`PersonelID, AdSoyad, Sicili, Maske, Aciklama, BildID, Rev, D1..D8`) kopyalanır; kaydı olmayanlar `"0"×40` ile gelir.
- Ekran **bir gün** gösterir (D1..D8 = o günün 8 saati); gün değişince maske içindeki ilgili 8 karakter güncellenir (`P8GunuSakla` ~6791, `P8Gun` ~6806). Satırda "tümü" düğmesi 8 saati birlikte açar/kapatır (`P8TumGun`). Açıklama ≤2000 (`P8SatirGecerli`).
- Kayıt (`P8Kaydet` ~6863) tek transaction:
  1. `P8KadroKontrol` (~7050): veritabanındaki bölüm kadrosu taslaktaki kişi kümesi ve sayısıyla birebir aynı olmalı (öncesinde ve sonunda) — `"Bölüm personel listesi değişmiş. Bölümü yeniden açın."`.
  2. **Her personel için** (değişmemiş olsa bile) tekil girişle aynı INSERT/UPDATE (`P8KayitSql` ~6853, aynı yetki/süre koşulu, Surum kontrolü) + `dmGunluk` kaydı. Tek bir hata hepsini geri alır (`"Kayıt başka kullanıcı tarafından değişmiş veya yetki/süre değişmiş: <ad>"`).
  3. Sonuç: `"<n> personelin beş günlük bildirimi kaydedildi."`; boş şablon "mazereti yok" olarak bildirilir.

#### 1.3.8 DMS Excel raporu — `P7DersExcel` (~5412)

- Dönem ve bölüm zorunlu; bölüm hesabı kendi bölümü. Kaydedilmemiş değişiklik varken alınamaz (rapor kayıtlı veriden).
- **Bölüm hesabı için**: bölümde bildirimi olmayan personel varsa rapor **verilmez** (`"Bölüm raporu alınamaz. Seçilen dönemde <n> personelin bildirimi eksik. …"`). Yönetici eksiklerle de alabilir (eksikler boş satır).
- Herhangi bir maske geçersizse rapor üretilmez.
- Dosya: `DMS_<DersDonemID>_<yyyymmdd_hhnnss>_<oturumKimliği>.xlsx`, sayfa `Haftalik Mazeretler`, tüm hücreler metin.
- Başlık 2 satır: A `Bölüm`, B `T.C.KN` (değer = `smPersonel.PersonelKodu`), C `Adı soyadı`, D `Sicili` (1–2. satır birleşik); E..AR = 5 gün × 8 sütun (1. satırda gün adı birleşik, 2. satırda `1..8`); AS `Genel açıklama`. Hücre değeri `"X"` (maskede `'1'`) veya boş. Satır sırası `BolumAdi, AdSoyad, PersonelKodu`. Ardından `R151Kimlik` ad sütununun önüne `Personel bölümü` ve `Sınıf / rütbe / unvan` sütunlarını ekler. Yatay A4, başlık `"DMS / <yıl> / <n>. dönem"`, alt bilgi `"X: mazeretli."`, ilk 4 sütun ve 2 satır dondurulur.

### 1.4 BDD — Branş Dağılımı (bd*)

> Ekran başlığı "BDD - Bölüm Ders Dozajı". Amaç: personelin dönem bazında bir **branşa** atanması ve branş başına DPS ders yükü ortalamasının hesaplanması.

#### 1.4.1 Tablolar (`BDDKur` ~satır 10503)

| Tablo | Alanlar | Kısıt |
|---|---|---|
| `bdBrans` | `BransID` COUNTER, `BolumID` LONG, `Ad` TEXT(100) | `uqBdBrans(BolumID,Ad)`; FK `smBolum` |
| `bdAtama` | `DonemID` (→`dmDonem.DersDonemID`), `PersonelID`, `BransID`, `Surum` | PK `(DonemID,PersonelID)` → **bir personelin bir dönemde tek branşı** olur |

Günlük tablosu yoktur. Kurulum DPS kurulumunu (`DPS11Hazir`) ön şart sayar.

#### 1.4.2 Yetki

- Asıl BDD ekranı (`bdAnaEkran`) yalnız **yönetici** (`B132Yetki` ~10061: `BDD132Hazir` + `P7Yetki("BDD")` + `P126Yetki`); yazma SQL'lerine `B132Auth` (yönetici + `ParolaSurum`) eklenir.
- Bölüm hesapları yalnız **salt-okunur bölüm raporu** görür (`ppBolumRapor`, `P141OkumaYetki` ~14448: bölüm hesabı olmalı, yönetici olmamalı, `ppModul` üzerinden BDD açık olmalı).

#### 1.4.3 Branş tanımı — `B132BransEkle` (~10151)

- Seçili bölüm için `Ad` 1–100 karakter (trim); `"Branş atanmamış"` adı (büyük/küçük harf duyarsız) ayrılmıştır; aynı bölümde aynı ad tekrar edemez (benzersiz indeks).
- `INSERT INTO bdBrans (BolumID,Ad) SELECT BolumID,<ad> FROM smBolum WHERE BolumID=… AND <B132Auth>`.
- Branş **yeniden adlandırma/silme ekranı yoktur** (kodda `bdBrans` için UPDATE/DELETE bulunmadı).

#### 1.4.4 Dönemlik atama — `B132Kaydet` (~10168)

- Personel seçilince mevcut atama ve `Surum` okunur (`B132PersonelSec`; yoksa `txtRev=0`).
- Koşullar (SQL içinde): yönetici oturumu; personel **seçili bölümde** (`smPersonel.BolumID=bid`); branş aynı bölüme ait (`bdBrans.BolumID=bid`).
- Yeni: `INSERT INTO bdAtama (DonemID,PersonelID,BransID,Surum) SELECT DersDonemID,pid,bran,1 FROM dmDonem WHERE DersDonemID=did <kosul>`.
- Değiştir: `UPDATE bdAtama SET BransID=…,Surum=Surum+1 WHERE DonemID=… AND PersonelID=… AND Surum=<rev> <kosul>`.
- Kaldır: `DELETE FROM bdAtama WHERE … AND Surum=<rev> <kosul>` (onay: `"Yalnızca seçili dönemdeki branş ataması kaldırılsın mı? DPS dersleri korunur."`).
- 1 satır etkilenmezse `"Atama, bölüm veya yetki değişmiş. Personeli yeniden seçin."`.

#### 1.4.5 Önceki dönemden kopyalama — `B132Kopyala` (~10206)

- "Karşılaştırma dönemi" (`cmbOnceki`) dönem seçilince otomatik önerilir: `OgretimYili < seçili` **veya** (aynı yıl ve `DonemNo <` seçili), sıralama `OgretimYili DESC, DonemNo DESC, DersDonemID DESC` ilk kayıt (`B132DonemSec` ~10100; yıl karşılaştırması metin olarak). Kullanıcı değiştirebilir; seçili dönemle aynı olamaz.
- SQL:
```sql
INSERT INTO bdAtama (DonemID,PersonelID,BransID,Surum)
SELECT <did>, A.PersonelID, A.BransID, 1
FROM (bdAtama AS A INNER JOIN bdBrans AS B ON A.BransID=B.BransID)
     INNER JOIN smPersonel AS P ON A.PersonelID=P.PersonelID
WHERE A.DonemID=<onceki> AND B.BolumID=<bid> AND P.BolumID=B.BolumID
  AND NOT EXISTS (SELECT * FROM bdAtama AS X WHERE X.DonemID=<did> AND X.PersonelID=A.PersonelID)
  AND <B132Auth>
```
- Yani yalnız seçili bölüm; mevcut atamalar değişmez; bölümü değişmiş personel aktarılmaz. Sonuç `"<n> personelin branşı aktarıldı."`.

#### 1.4.6 Yük hesabı — `B132Hesap` (~10239)

- Dönemde `dpAtama.Saat Is Null OR Saat<0` varsa hesap durur (`"DPS'de eksik veya negatif ders yükü var; …"`).
- Personel yükü (`B132YukSql`): `SELECT A.PersonelID, Sum(A.Saat) AS DS FROM dpAtama AS A INNER JOIN dpDers AS D ON A.DersID=D.DersID WHERE D.DonemID=<did> GROUP BY A.PersonelID` → **tüm planlayan bölümlerdeki** DPS görevleri, ek uygulama dahil.
- Branş üyeleri (`B132UyeSql`): `bdAtama` ⨝ `smPersonel` ⨝ `bdBrans`, `A.DonemID=did` (+ `B.BolumID=bid` filtresi; bid=0 → tüm bölümler).
- Özet (branş başına): `Toplam Branşın DS = Σ DS(üyeler)`, `Öğretim Elemanı Sayısı = üye sayısı` (yükü 0 olanlar dahil), `Ortalama Ders Yükü = Toplam / Sayı` (üye yoksa boş/Null). Personelsiz branşlar da listelenir.
- Ayrıntı: her üye için `Dönem, Bölüm (branşın bölümü), Branş, ID, Personel, Personel sınıfı, Rütbe, Unvan, Toplam DS`.
- **Eksik atama raporu** (`B132EksikSql` ~10233): `smPersonel` içinde o dönemde `bdAtama` kaydı olmayan herkes (bölüm filtresi personelin **güncel** `BolumID`'si), branş adı `"Branş atanmamış"`, DS gösterilir; ortalamalara katılmaz. Ekran durum satırı eksik sayısını verir.
- Karşılaştırma dönemi seçiliyse aynı hesap o dönem için de yapılıp özet/ayrıntıya eklenir (`B132Veri` ~10333).
- Hesap bir okuma transaction'ı içinde yapılır (tutarlı anlık görüntü amaçlı).

#### 1.4.7 BDD çıktıları

- **Excel** `B132Excel` (~10362), dosya `BDD_Ders_Dozaji_<ts>_<salt>.xlsx`: `Branş özeti` (`Dönem, BÖLÜM, Branş, Toplam Branşın DS, Öğretim Elemanı Sayısı, Ortalama Ders Yükü`; sayılar `0.00`, sayı sütunu `0`), `Personel ayrıntısı` (`Donem, Bolum, Brans, Personel ID, Personel, Toplam DS`; ad önüne `Personel bölümü`, `Sınıf / rütbe / unvan` eklenir), `Hesap bilgisi` (hesap açıklamaları; ör. "Ortalama = toplam DS / o dönemde branşa atanmış personel sayısı. Sıfır yükü olan personel sayıya dahildir.").
- **Tüm bölümler** (`R148Veri`, kod `BDD`): `B132Hesap(did, 0, …)` + karşılaştırma dönemi; Özet başlıkları `Dönem, Bölüm, Branş, Toplam branş DS, Personel sayısı, Ortalama ders yükü`.
- **Bölüm hesabı raporu** `P141Bdd` (~14504): kendi bölümünün güncel personelini dolaşır; DS = o dönemdeki `Σ dpAtama.Saat`; personelin branşı kendi bölümünün branşı değilse `"Brans / bolum uyumsuz - yonetici kontrolu"`, yoksa `"Brans atanmamis"`. Excel `BDD_Bolum_<BolumID>_<ts>_<salt>.xlsx` (`Brans ozeti`, `Personel raporu`).
- Not: yönetici raporu üyeliği **branşın bölümüne** göre, bölüm raporu **personelin güncel bölümüne** göre gruplar; bölüm değiştiren personelde iki rapor farklı sonuç verebilir.

---

## 2. Platform, kimlik doğrulama ve yetki (pp*, smKullanici)

### 2.1 Hesap tablosu `smKullanici`

| Alan | Tip | Anlam / kaynak |
|---|---|---|
| `Kullanici` | TEXT(50) PK | Kullanıcı adı; 1–50 karakter, CR/LF yok; mevcut hesabın adı değiştirilemez (`A143Kaydet` ~15177) |
| `BolumID` | LONG, FK `smBolum` | Bölüm hesabında zorunlu; yöneticide "bağlı olduğu bölüm" (bilgi amaçlı); ana yöneticide Null |
| `Yonetici` | YESNO | `True` = yönetici |
| `Tuz` | TEXT(32) | 16 bayt rastgele tuz, 32 büyük harf hex |
| `Parola` | TEXT(64) | 32 bayt PBKDF2 çıktısı, 64 büyük harf hex |
| `ParolaSurum` | LONG, varsayılan 0 | Oturum geçersizleştirme sayacı (2.3) — `V49HesapAlani` ~2383 |
| `AnaYonetici` | TEXT(10) | `'ANA'` veya Null; **benzersiz indeks `smUX49Ana … WITH IGNORE NULL`** → tek ana yönetici (`V49Guncelle` ~2294) |
| `HesapAktif` | YESNO, varsayılan True | Pasif hesap giriş yapamaz (`A143Sema` ~15074) |

### 2.2 Parola özeti algoritması (`V4Hash` ~493, `V4Salt` ~508)

- **Algoritma:** PBKDF2-HMAC-SHA256, Windows CNG (`bcrypt.dll`: `BCryptOpenAlgorithmProvider("SHA256", flags=8 = BCRYPT_ALG_HANDLE_HMAC_FLAG)` + `BCryptDeriveKeyPBKDF2`).
- **Parola baytları:** VBA dizesinin iç gösterimi → **UTF-16LE**, BOM ve sonlandırıcı yok (`StrPtr(password)`, uzunluk `LenB(password)`).
- **Tuz:** `BCryptGenRandom(…, flags=2 = BCRYPT_USE_SYSTEM_PREFERRED_RNG)` ile 16 bayt; `Tuz` alanında 32 karakterlik **büyük harf hex** olarak saklanır; hesaplamada hex → bayt çevrilir (uzunluk 32 değilse hata).
- **İterasyon:** **600.000**. Kodda `Currency` tipinde `60@` geçirilir; Currency 64-bit tamsayıyı 10.000 ölçekli tuttuğu için ham değer 600.000'dir (kod yorumu bunu açıkça belirtir).
- **Çıktı:** 32 bayt → 64 karakter **büyük harf hex** (`Hex$` + sıfır doldurma).
- **Doğrulama:** `StrComp(hash, Parola, vbBinaryCompare)` — büyük/küçük harf duyarlı tam eşitlik. Kullanıcı adı araması Access SQL'inde büyük/küçük harf **duyarsızdır**.
- **Parola politikası:** en az 6 karakter, iki kez aynı girilmeli. Karmaşıklık, süre dolumu, hatalı deneme kilidi veya hız sınırı **yoktur**.

Python eşdeğeri (doğrulama için):

```python
import hashlib, hmac
def ppys_hash(parola: str, tuz_hex: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", parola.encode("utf-16-le"),
                             bytes.fromhex(tuz_hex), 600_000, dklen=32)
    return dk.hex().upper()
def ppys_dogrula(parola, tuz_hex, parola_hex):
    return hmac.compare_digest(ppys_hash(parola, tuz_hex), parola_hex)
```

> **Django notu:** Django'nun `PBKDF2PasswordHasher`'ı parolayı **UTF-8** ile kodlar; bu nedenle mevcut özetler doğrudan Django'ya aktarılamaz. Seçenekler: (a) `encoded = "ppys_pbkdf2_utf16$600000$<tuz>$<özet>"` biçiminde özel bir `BasePasswordHasher` yazıp ilk başarılı girişte Django'nun varsayılan hasher'ına yükseltmek (`must_update` → True), ya da (b) tüm kullanıcılara parola sıfırlatmak.

### 2.3 Giriş akışı ve oturum (`V4GirisKaydet` ~638, `V4Baslat` ~690, `V43OturumGecerli` ~1116)

1. Ortak veri dosyasının yanında `<veri>.ppys-bakim.json` varsa (yarım kalmış yedekten dönüş) **giriş durur** (`R131BakimVar` ~9623).
2. Kullanıcı adı ve parola boş olamaz; kullanıcı yoksa veya özet uyuşmazsa **aynı genel mesaj**: `"Kullanici adi veya parola hatali."` (kullanıcı adı ifşa edilmez).
3. Bakım modu açıksa yalnız ana yönetici girebilir (`B144GirisKontrol` ~15424).
4. `HesapAktif=False` → `"Bu hesap etkin değil. Admin ile görüşün."`
5. Oturum değişkenleri: `v4User`, `v4Admin` (= `Yonetici`), `v4Bolum` (= `BolumID`), `v49SessionRev` (= girişteki `ParolaSurum`).
6. Hiç hesap yoksa giriş ekranı "ilk" kipinde açılır ve **ilk yönetici** oluşturulur (yalnız tablo boşken).

**`ParolaSurum` anlamı:** hesap başına "güvenlik damgası". Parola sıfırlama, bölüm değişikliği, yönetici modül yetkisi değişikliği, etkin/pasif değişikliği gibi her hesap güncellemesinde `ParolaSurum=ParolaSurum+1` yapılır (`V4GirisKaydet` ~676, `V49ParolaKaydet` ~2496, `A143Kaydet` ~15198). Oturumun sakladığı değerle veritabanındaki değer farklıysa oturum geçersizdir → kullanıcı yeniden giriş yapmak zorunda kalır. Ayrıca yazma SQL'lerinin çoğuna `EXISTS (SELECT * FROM smKullanici WHERE Kullanici=… AND ParolaSurum=…)` koşulu gömülüdür; eski oturumdan gelen yazma 0 satır etkiler.

**Oturum geçerliliği** (`V43OturumGecerli`), hemen her işlemde yeniden hesaplanır:
- kullanıcı satırı hâlâ var, `Yonetici` ve `BolumID` oturumdakiyle aynı,
- `ParolaSurum` aynı, `HesapAktif=True`,
- yedekten dönüş işareti yok,
- bulunulan modül için izin var (`Y134Izin`, 2.5),
- bakım süresi dolmamış (`B144OturumAcik`, 2.7).

Çıkış/oturum değiştirme `V527OturumDegistir` (~3499) yerel değişkenleri temizler. Oturum kimliği `V6OturumKimligi` (~3737) Access süreci başına rastgele 32 hex (geçici taslak tabloları ve bakım istemci kaydı için).

### 2.4 Hesap yönetimi

| İşlem | Kim | Kaynak | Kural |
|---|---|---|---|
| İlk yönetici | Tablo boşken herkes | `V4GirisKaydet` ("ilk") | `Yonetici=True`, `BolumID=Null` |
| Bölüm hesabı ekle / parola+bölüm yenile | Ana yönetici, PKS modülünde | `V4GirisKaydet` ("hesap") | Bölüm zorunlu; yönetici hesabı bu ekrandan değiştirilemez; mevcutsa `ParolaSurum+1`, yeni tuz+özet |
| Yönetici ekle / güncelle, modül yetkileri, etkin/pasif | Ana yönetici | `A143Kaydet` (~15177) | Bkz. aşağı |
| Yönetici parolası sıfırla | Ana yönetici | `V49ParolaKaydet` (~2496) | Hedef `Yonetici=True AND AnaYonetici Is Null`; `ParolaSurum+1` |

`A143Kaydet` kuralları: kullanıcı adı 1–50, CR/LF yok, mevcut hesapta değişmez; bölüm zorunlu ve var olmalı; yeni hesapta parola zorunlu, mevcutta boş bırakılırsa değişmez; tek transaction içinde `ppYetkiKilit` artırılır, ana yönetici yetkisi transaction içinde tekrar doğrulanır; güncelleme `WHERE … AND ParolaSurum=<ekranda okunan>` (iyimser); ana yönetici hesabı bu ekrandan değiştirilemez; `ppYoneticiModul` satırları silinip tüm modül kodları için `Acik` True/False olarak yeniden yazılır; `ppYetkiGunluk(Tarih, Admin, Hesap, Islem='Yeni yönetici'|'Yetki güncelleme', Ayrinti='Bölüm=…; Etkin=…; Modüller=…')`. Her kayıt `ParolaSurum+1` yaptığı için ilgili yönetici yeniden giriş yapmalıdır.

### 2.5 Modül erişimi (`Y134Izin` ~12076, `A143Izin` ~15049, `U161Izin` ~20261)

- **`ppModul(Kod, Acik)`**: modülün **bölüm hesaplarına** genel olarak açık/kapalı olması. Bölüm hesabı için `PKS, SMS, DMS, DPS, STS, BDD, SPS, DDS` kodlarında `Acik` okunur; `DZN` bölüm hesabına **her zaman kapalı**; `BDD`/`SPS` ayrıca 1.41 kurulumu ister. (Not: SPS ve BDD'nin ana ekranları ayrıca yönetici şartı koyar; bölüm hesabı BDD'de yalnız salt-okunur bölüm raporunu görür.)
- **`ppYoneticiModul(Kullanici, Kod, Acik)`**: **yöneticinin** hangi modülleri kullanabileceği. Ana yönetici her şeye erişir; diğer yöneticiler için `HesapAktif=True` ve `ParolaSurum` eşleşmesi + ilgili satırın `Acik=True` olması gerekir. `""`, `AYAR`, `PPYS` kodları etkin yöneticilere hep açıktır. Tablo ilk kurulduğunda mevcut tüm yöneticilere tüm modüller açık yazılır.
- Ayar ekranındaki düğmeler modül yetkisine göre gösterilir (`A143AyarGorunum` ~15242): yedek/bakım/silme/hesap düğmeleri yalnız ana yöneticiye.
- Menü rotaları (`U161Rotalar` ~20210): her sayfa bir modül koduna bağlıdır; bölüm hesabı SPS alt sayfalarını, DDS "Program aktarımı", "ÜYBS aktarımı" ve PKS "Personel sıralaması" sayfalarını göremez (`U161RolGorur`).
- Yönetici ayar sayfası notu (kodda): *"Yönetici, açılan modüllerde tüm bölümlerde işlem yapabilir. Hesap / yetki yönetimi ve DDS kesinleştirmesi yalnız admine aittir."*

**Ana yönetici yetkileri (kodda `V49AnaYetki`/`A143Ana` arayan işlemler):** hesap ve modül yetkileri, yönetici parola sıfırlama, bakım modu, yedekten geri dönüş, veri temizliği düğmeleri, DDS `Kesin`/`Iptal`, DPS ders Excel aktarımı (`D11Master`), SMS kapsam değişikliği ve kesinleştirme kaldırma (P151), PKS bölüm hesabı tanımları.

### 2.6 Eşzamanlılık kalıbı (Surum + *Kilit)

Access çok kullanıcılı bir ortak `.accdb` üzerinde çalıştığı için üç teknik birlikte kullanılır:

1. **Satır sürümü (iyimser kilit):** Ekran açılırken `Surum` okunur; kayıtta
   `UPDATE <tablo> SET …, Surum=Surum+1 WHERE <PK> AND Surum=<okunan> [AND <yetki koşulu>]`
   çalışır ve `RecordsAffected <> 1` ise işlem geri alınır, kullanıcıya "başka kullanıcı değiştirdi / yeniden açın" denir. Örnekler: `smBildirim` (`SM_Kaydet` ~408), `dmBildirim` (`P7DersKaydet` ~5210), `dmDonem` (~5327), `dpDers` (~8392), `dpBolumKisim` (~9411), `bdAtama` (~10189), `spRol` (~11577), `dpMekan` (~12897), `stDonem` (~7358), `spPlan` (`S133DB`). Yeni kayıt için beklenen sürüm 0'dır ve benzersiz indeks çift eklemeyi engeller. Sürüm her başarılı kayıtta ilgili `*Gunluk` tablosuna da yazılır.
2. **Tek satırlık kilit tabloları (global muteks):** `ddKilit`, `spKilit`, `pp151Kilit`, `ppYetkiKilit`, `ppBakimDurum`. Transaction başında `UPDATE <xKilit> SET Surum=Surum+1 WHERE ID=1` çalıştırılır; Jet bu satırın kilidini commit'e kadar tuttuğu için aynı modülde aynı anda **tek yazma işlemi** ilerler. Değer okunmaz. DPS'te aynı amaçla `UPDATE dmDonem SET DonemNo=DonemNo …` "sahte güncelleme" kullanılır (`D138Kilit` ~13013).
3. **Transaction içinde yeniden doğrulama:** yetki (`D140Yetki`, `P126Kosul`, `D11Auth` …), seçimin hâlâ geçerliliği (`D140Aktif`, `D142Secim`), durum koşulu (`WHERE Durum=<önceki>`), ve rapor öncesi/sonrası damga karşılaştırması (`D11Damga`, `S10Stamp`).

### 2.7 Bakım modu ve istemci nabzı (`B144*` ~15381–15760, `B149*` ~16264)

Tablolar: `ppBakimDurum` (tek satır: `Aktif`, `Surum`, `Dakika` 1–30, `Baslatan`, `Baslangic`, `Zorla`), `ppBakimIstemci` (`Oturum` PK, `Bilgisayar`, `Kullanici`, `SonGorulme`, `Durum`, `Surum`, `IstemciSurum`), `ppBakimGunluk` (`Tarih`, `Kullanici`, `Islem`).

- Ana yönetici bakımı 1–30 dakikalık süreyle başlatır (isteğe bağlı **zorunlu kapatma**). Zaten açıksa süre yeniden başlatılmaz. Başlatma/bitirme `ppBakimGunluk`'e yazılır.
- Bakım açıkken **yeni girişler kapalıdır** (ana yönetici hariç).
- Her istemci gizli bir zamanlayıcı formuyla **10 saniyede bir** `ppBakimDurum`'u okur (`B144Tik`) ve `ppBakimIstemci`'ye nabız yazar. Bakımın yeni `Surum`'unu ilk gördüğünde kendi yerel saatine göre `şimdi + Dakika` son süresini hesaplar, geri sayım uyarısı gösterir.
- Süre dolunca: o istemcinin oturumu geçersiz sayılır (yeni işlem yapılamaz); açık çalışma ekranı yoksa uygulama kendini kapatır; varsa uyarıda bekler. `Zorla=True` ise ana yönetici dışındaki istemciler süre sonunda zorla kapatılır (`B149Kapat`, `TerminateProcess`).
- Yönetici ekranı istemcileri listeler; 45 saniyedir nabız gelmeyen istemci "Yanıt yok; kapanış doğrulanmadı" olarak gösterilir. `B144KilitKontrol` ortak veri dosyasını özel kipte açmayı deneyerek kimsenin bağlı olmadığını doğrular.

Bu mekanizmanın tamamı, dosya tabanlı Access'te sürüm güncellemesi/yedekleme için herkesi dışarı çıkarmaya yöneliktir (Bölüm 4.4).

### 2.8 Yedekleme ve veri temizliği

- **Yedek / geri dönüş** (`R131*` ~9615–10046): eski sürümde yönetici yedek alabiliyordu; 1.43 kurulumundan sonra (`A143Kontrol`) yedek alma da **yalnız ana yöneticiye** açıktır; geri dönüş her durumda yalnız ana yönetici. İşlem, PowerShell betiği yazılıp çalıştırılarak, dosyalara özel erişimle yapılır; süreç boyunca `<veri>.ppys-bakim.json` işaret dosyası tüm girişleri durdurur.
- **Veri temizliği** (`P126Kapsam`/`P126Plan` ~9037–9105; 1.43 sonrası yalnız ana yönetici): 1 tüm SMS bildirimleri; 2 seçili sınav dönemi (SMS + STS verisiyle); 3 tüm sınav dönemleri; 4 seçili personel (SMS, DMS, STS, DPS atamaları, BDD, SPS rolü dahil, ilgili `dpDers`/`stDonem` sürümleri artırılarak); 9 seçili öğretim dönemi (DMS, DPS, BDD). Silme engelleri: DDS arşivi (`D140SilmeKontrol`), SPS (`S133SilmeKontrol`).

### 2.9 Denetim günlükleri (özet)

| Tablo | İçerik |
|---|---|
| `smGunluk` | Kim, ne zaman, hangi sürüm (içerik yok) |
| `dmGunluk` | Her kayıtta maske + açıklamanın tam anlık görüntüsü |
| `dpGunluk` | Atama değişiklikleri (`Islem` metinli) |
| `ddGunluk` | DDS işlemleri (1.1.14) |
| `spGunluk`, `stGunluk` | SPS işlem metni, STS anlık görüntü |
| `pp151Gunluk` | SMS kapsam / kesinleştirme / sıralama |
| `ppYetkiGunluk` | Yönetici hesap ve yetki değişiklikleri |
| `ppBakimGunluk` | Bakım başlat/bitir |

Kodda hiçbir günlüğü kullanıcıya gösteren ekran yoktur.

---

## 3. Sınav Modülleri (SMS / SPS / STS)

Kaynak: `MazeretKurulum.mod.bas`. Satır numaraları yaklaşıktır (`~`). Form/kontrol yerleşimi, renk, ikon kodu atlanmıştır. Üç modül birbirine bağlıdır:

- **SMS** (Sınav Mazeret Sistemi): personelin sınav dönemindeki gün / yarım gün mazeret bildirimi.
- **SPS** (Sınav Planlama Sistemi): öğrenci–sınav–seans–salon planı ve gözetmen (görevli) dağıtımı. Uygunluk SMS'ten, adalet skoru STS'den okunur.
- **STS** (Skor Takip Sistemi): personelin dönemlik hafta içi / hafta sonu sınav görevi sayıları ve haftalık ders saati; adalet skoru üretir. Kesinleşen SPS planları STS toplamlarına eklenir.

---

### 3.1 SMS – Sınav Mazeret Bildirimi

#### 3.1.1 Veri modeli

| Tablo | Alanlar / anahtarlar | Not |
|---|---|---|
| `smDonem` | `DonemID`, `DonemAdi`, `IlkGun`, `SonGun`, `GiriseAcik` (YESNO, varsayılan False), `SonBildirim` (DATETIME, null = sınırsız), `TamGun` (YESNO, varsayılan False) | `MazeretKur` (~103), `V4Guncelle` (~550), `V45Guncelle` (~1517) |
| `smGun` | `GunID`, `DonemID`, `Tarih`; UNIQUE(`DonemID`,`Tarih`) | Dönemin sınav günleri |
| `smBildirim` | `BildirimID`, `PersonelID`, `DonemID`, `KayitZamani`, `Surum` (varsayılan 1), `Aciklama` TEXT(255); UNIQUE(`PersonelID`,`DonemID`) | Kişi başına dönemde **tek** bildirim |
| `smMazeret` | `MazeretID`, `BildirimID`, `DonemID`, `Tarih`, `OO` YESNO, `OS` YESNO; UNIQUE(`BildirimID`,`Tarih`); FK (`DonemID`,`Tarih`)→`smGun` | Bildirimdeki her gün için bir satır |
| `smGunluk` | `IslemID`, `BildirimID`, `Kullanici`, `IslemZamani`, `Surum` | Denetim izi: kim, ne zaman, hangi sürüm. **İçerik (eski/yeni değer) tutulmaz.** (~546) |
| `sms151Donem` | `DonemID` | Döneme kapsam başlatıldı işareti (~17113) |
| `sms151Kapsam` | PK(`DonemID`,`PersonelID`), `Dahil` | Personel bu dönemin SMS kapsamında mı |
| `sms151Kesin` | PK(`DonemID`,`BolumID`), `Kesin` | Bölüm bazında kesinleştirme |
| `pp151Sira` | PK(`PersonelID`,`Tur`), `Sira` | Liste sırası; `Tur`=`"Y"` (yönetici/admin ortak) / `"B"` (bölüm rapor sırası) |
| `pp151Gunluk` | `ID`, `Tarih`, `Hesap`, `Islem`, `Ayrinti` | Kapsam/kesinleştirme/sıra işlemleri günlüğü (`P151Log` ~16761) |
| `pp151Kilit` | `ID`=1, `Surum` | Global yazma kilidi (`P151Kilit` ~16756) |
| `smV47Secenek` | `SecenekID`, `Tur` (`"S"` Sınıf / `"R"` Rütbe / `"U"` Unvan), `Metin`(≤40), `Aktif`, `Onde`, `SecSurum`, `KaynakKod` | Personel unvan seçenekleri (PKS'e ait, SMS ekranında kullanılır) |
| `smV6Taslak`, `smV6Matris` | `OturumID` (32 hex) + taslak satırlar | **Yerel** (front-end) taslak tabloları; Access'e özgü |

`OO` = **Öğleden Önce**, `OS` = **Öğleden Sonra** (ekran etiketleri "Ogle oncesi"/"Ogle sonrasi", Excel başlıkları "ÖÖ"/"ÖS"). İşaretli = **mazeretli (görev verilemez)**, boş = **müsait** (`MazeretKur` ~181).

#### 3.1.2 Dönem kuralları

- **Yeni dönem** (`SM_YeniDonem` ~445): yalnız yönetici. Ad + ilk/son tarih; aralık **1–62 gün** (`DateDiff>61` reddedilir). Aralıktaki **hafta sonları dahil tüm günler** `smGun`'a eklenir. Yeni dönem `GiriseAcik=False` doğar; bildirim biçimi oluştururken seçilir: `TamGun=True` ("tarih başına tek kutu") veya OO/OS ("tarih başına iki kutu"). P151 kuruluysa aynı işlemde `P151DonemKur` ile kapsam başlatılır.
- **Gün düzenleme**: Kodda dönem günlerini sonradan ekleme/çıkarma işlevi **yok**; SPS mesajları "önce SMS dönem günlerini düzenleyin" diyor (~11063). → belirsiz / açık soru.
- **Bildirim biçimi değiştirme** (`V45BicimDegistir` ~1590): yalnız dönemde hiç `smBildirim` yoksa; SQL'de `DonemID NOT IN (SELECT DonemID FROM smBildirim)` koşulu ile yarış güvenli.
- **Girişe aç/kapat** (`V4Islem(4)` ~787): `GiriseAcik` tersine çevrilir. **Son bildirim zamanı** (`V4Islem(5)` ~791): tarih-saat girilir veya `"SINIRSIZ"` → `SonBildirim=Null`.
- **Yazılabilirlik** (`V4Yetki` ~734, `V5211DonemYazilabilir` ~3710): yazma için `GiriseAcik=True` **ve** (`SonBildirim` null **veya** `Now() <= SonBildirim`). Mesajlar: "Bu donem bildirim girisine kapali.", "Son bildirim zamani gecti.".
  - **İstisna:** P151 kuruluysa ve kullanıcı admin ise (SMS yetkili) dönem kapalı/süre geçmiş olsa da yazabilir (`V4Yetki` ~744 erken `True`; `V5211` ~3715).
- **Tam gün dönem**: kayıtta `OS=OO` zorlanır (`SM_Kaydet` ~389); yüklemede/raporda `OO<>OS` satırı hata kabul edilir ("Tam gun doneminde yarim gun kaydi var").

#### 3.1.3 Kim kimin adına girer

- Oturum: `smKullanici` (`Yonetici` bayrağı, `BolumID`). Bölüm hesabı (`Yonetici=False`) yalnız **kendi bölümündeki** personel için okur/yazar (`V4Yetki` ~738, `P151YazmaKontrol` ~16823). Yönetici tüm bölümler.
- P151 kapsamı: personel o dönemin `sms151Kapsam` kaydında `Dahil=True` değilse listede görünmez ve yazılamaz ("Personel bu dönemin SMS kapsamına dahil değil", ~16822).
- Bölüm **kesinleştirilmişse** bölüm hesabı yazamaz ("Bölüm kesinleştirildi. Değişiklik için yöneticiye başvurun.", ~16825); yönetici yazabilir.
- Oturum geçerliliği her kritik adımda yeniden doğrulanır (`V43OturumGecerli` ~1116): kullanıcı hâlâ var, yönetici/bölüm bilgisi değişmemiş, `ParolaSurum` aynı, hesap aktif, modül izni (`Y134Izin`), bakım kilidi yok.

#### 3.1.4 Bildirim kaydı

**Tekil ekran** (`SM_Yukle` ~291, `SM_Kaydet` ~379):
1. Personel + dönem seçilir, "Günleri aç": `smGun`'daki tüm tarihler taslağa (`OO=False, OS=False`) kopyalanır; mevcut bildirim varsa `smMazeret` değerleri üzerine yazılır; `Surum` okunur ve okuma sırasında değiştiyse iptal.
2. Kayıt koşulları: taslak satır sayısı = `smGun` satır sayısı ("Donemin gunleri eksik"); seçim değişmemiş; yetki ve dönem yazılabilir.
3. Tek transaction: `pp151Kilit` artırılır → bildirim yoksa `INSERT smBildirim(...,Surum=1)`; varsa **iyimser kilit** `UPDATE ... SET Surum=Surum+1 WHERE BildirimID=? AND Surum=<okunan>` (etkilenen ≠1 → "başka bir kullanıcı tarafından değiştirildi") → `DELETE smMazeret` + tüm günler yeniden `INSERT` → `INSERT smGunluk(BildirimID, Kullanici, Now, yeniSurum)`.
4. **Mazereti olmayan da kaydetmek zorunda**: "Henuz bildirim yok. Mazeretiniz yoksa da BILDIRIMI KAYDET dugmesine basin." (~323). Bildirimsiz kişi SPS'te **müsait sayılmaz**.

**Toplu bölüm ekranı** (`V44Ac` ~1244, `V44Kaydet` ~1386):
- Bölüm + dönem; personel listesi (kapsamdaki) matris olarak açılır (her gün için `GxxO`/`GxxS`, en çok 62 gün). Satır durumu: `"Bekleniyor"` (bildirim yok) / `"Kayitli"`.
- Kaydet **listelenen tüm personeli** kaydeder (Bildir sütunu V52 ile gizlenmiş; "Isaretsiz gunler musait sayilir", ~1399). Tek transaction, her satır için ayrı iyimser `Surum` kontrolü, bölüm değişmişse iptal, dönem takvimi değiştiyse iptal, commit öncesi dönem yazılabilirliği tekrar kontrol. `Aciklama` (≤255) bildirim düzeyinde.

#### 3.1.5 Durumlar (tam literal) ve hesaplanışı

Rapor sorgusu `smRaporDetay` (`MazeretKur` ~129), her personel × tarih × yarım gün için:

```
IIf(BildirimID Is Null,'Bekleniyor',
  IIf(MazeretID Is Null,'Eksik kayit',
    IIf(M.OO,'Mazeretli','Musait')))      -- OgleOncesi; OgleSonrasi için M.OS
```

| Literal | Anlamı |
|---|---|
| `'Bekleniyor'` | Kişinin bu dönem için `smBildirim` kaydı yok |
| `'Eksik kayit'` | Bildirim var ama o tarih için `smMazeret` satırı yok (veri tutarsızlığı) |
| `'Mazeretli'` | İlgili yarım gün işaretli |
| `'Musait'` | İlgili yarım gün işaretsiz |

Diğer sorgular: `smRaporBeklenen` (bildirimi olmayanlar), `smQOturum`/`smRaporMatris` (personel × "yyyy-mm-dd OO/OS" pivot), `smRaporSayilar` (tarih başına `OO_Musait`, `OS_Musait`, `OO_Mazeretli`, `OS_Mazeretli`, `Beklenen`, `EksikKayit`). P151 sonrası `smQBeklenen` yalnız `Dahil=True` kapsamı içerir (~17147).

Diğer ekran/Excel literalleri: matris `"Bekleniyor"`/`"Kayitli"` (~1295); Excel `"Bildirim bekleniyor"` / `"Bildirildi"`, hücrede `"X"` = mazeretli, boş = yalnız bildirildi durumundakiler için müsait (`V52Rapor` ~2921, ~2945, ~2973); kapsam listesinde `'Dahil'` / `'Hariç'` (~16941).

#### 3.1.6 Kapsam (P151) ve bölüm kesinleştirme

- **Kapsam başlatma** (`P151DonemKur` ~16770): dönem ilk kez kullanıldığında, `IlkGun`'a göre bir önceki kapsamlı dönemin `sms151Kapsam` listesi kopyalanır; önceki yoksa tüm personel `Dahil=True`.
- **Kapsam değiştirme** (`P151KapsamKaydet` ~16966): yalnız ana admin (`A143Ana`). Değişen her kişinin bölümünün `sms151Kesin.Kesin=False` yapılır; eski bildirimler silinmez; günlüğe "SMS dahil"/"SMS hariç".
- **Kesinleştir** (`P151Kesinlestir(False)` ~16839): bölüm hesabı (kendi bölümü) veya admin. Koşullar: açık değişiklik yok; dönem yazılabilir; bölümdeki kapsamdaki **her** personelin tam 1 bildirimi ve `smGun` sayısı kadar dolu mazeret satırı olmalı ("Bildirimi eksik personel", "Gün bilgileri eksik personel"). Sonuç `sms151Kesin(DonemID,BolumID,Kesin=True)`; günlük "Bölüm kesinleştirildi".
- **Kesinleştirmeyi kaldır** (`P151Kesinlestir(True)`): **yalnız admin**. Dönem yazılabilirlik kontrolü yapılmaz.
- **Rapor kilidi** (`P151RaporKontrol` ~16829): bölüm hesabı Excel raporunu yalnız **bölüm kesinleştirildikten sonra** alabilir; admin her zaman.

#### 3.1.7 Raporlar

- Yönetici sorguları (`SM_Rapor` ~427): matris / bildirim beklenenler / günlük sayılar.
- Excel (`V52Rapor` ~2823): sütunlar T.C.KN, Adı soyadı, Sicili, her gün için ÖÖ/ÖS (tam günde "Tüm gün"), Açıklama, Bildirim durumu. Bölüm hesabı başka bölüm alamaz. Kayıtlar takvimle birebir uyuşmalı (eksik/fazla gün → hata). Aktarım sırasında bildirim eklendi/silindi/`Surum` değiştiyse rapor iptal edilir (tutarlı anlık görüntü). Ad yanına sınıf/rütbe/unvan (`R130Kimlik`) eklenir, sıralama `pp151Sira` (`R151Sirala` ~17190).

#### 3.1.8 Personel adı / unvan kuralları (V47, kısaca)

- Görünen ad (`V47Birlestir` ~2029): Unvan `Onde=True` ise `Unvan + Sınıf+Rütbe + Ad`, aksi halde `Sınıf+Rütbe + Unvan + Ad`.
- Sınıf veya rütbe seçiliyse unvan `Öğt.Gör.` / `Öğt.Gör.Dr.` (normalize: `"ogtgor"`, `"ogtgordr"`) olamaz (`V52YasakUnvan` ~3111, `V52UnvanDogrula` ~3138).
- Pasif seçenek mevcut kayıtlarda korunur, yeni seçimde sunulmaz. Personel güncelleme `BilgiSurum` iyimser kilitli. (Asıl sahibi PKS modülü.)

#### 3.1.9 Temizlik / silme (SMS verisi)

`V43Kapsam`/`V43Plan` (~956–1025): kapsamlar 1 tüm bildirim+mazeret+günlük, 2 seçili dönem (gün ve dönem dahil), 3 tüm dönemler, 4 tek personel, 8 bölüm giriş hesapları; 5/6/7 (toplu personel/bölüm silme) kapatılmış. SPS'e bağlı dönem/personel silinemez (`S133SilmeKontrol` ~11866).

---

### 3.2 SPS – Sınav Planlama ve Görevli Dağıtımı

#### 3.2.1 Veri modeli (`S133Sema` ~10555, `S152`, `S157Sema` ~18629)

| Tablo | İçerik |
|---|---|
| `spPlan` | `PlanID`, `Ad`(≤100), `DonemID` (SMS dönemi, **UNIQUE** → dönem başına tek plan), `ReferansID` (STS "Z referans" dönemi), `Gunluk` (öğrenci başına günlük sınav sınırı; 0 = o günün seans sayısı), `Durum` (`'Taslak'`/`'Kesin'`), `Surum`; 1.52: `DinGunluk`, `DinArdisik`, `DinAra`, `GorevSiniri`; 1.57: `SeansGunler`, `SeansSaat`, `SeansIlk`, `SeansSon`, `RaporBaslik` |
| `spSeans` | `SeansID`, `PlanID`, `Baslangic`, `Bitis`; UNIQUE(`PlanID`,`Baslangic`) |
| `spSalon` | `SalonID`, `PlanID`, `MekanID` (→`dpMekan`), `Kapasite`, `Uyruk` (kural metni), `Manuel` (= uygulama salonu); UNIQUE(`PlanID`,`MekanID`) |
| `spOgrenci` | PK(`PlanID`,`OgrNo`), `Sinif` (`"1"`/`"2"`), `Kisim`, `AdSoyad`, `Uyruk` |
| `spSinav` | `SinavID`, `PlanID`, `Kod`, `Ad`, `Tur`, `SeansID` (null = planlanmadı); UNIQUE(`PlanID`,`Kod`,`Tur`); 1.57: `RaporDonem`, `Malzeme` |
| `spKayit` | PK(`SinavID`,`OgrNo`), `PlanID`, `SalonID` (null = salonsuz), `Istisna` |
| `spIhtiyac` | PK(`SeansID`,`SalonID`,`Rol`), `Sayi`, `Ozel` (yönetici elle belirledi) |
| `spRol` | PK(`PersonelID`), `Rol` (`"A"`/`"G"`/`"T"`), `Surum` – **plan bağımsız, kişi başına tek rol** |
| `spGorev` | `GorevID`, `PlanID`, `SeansID`, `SalonID`, `PersonelID`, `Rol`, `Manuel`, `AtamaSkoru`; **UNIQUE(`SeansID`,`PersonelID`)** |
| `spAktar` | PK(`PlanID`,`PersonelID`), `HaftaIci`, `HaftaSonu` – kesinleşen planın STS katkısı |
| `spSorun` | `ID`, `PlanID`, `Aciklama`(≤255) – planlanamayan/kontrol sonuçları |
| `spGunluk` | `ID`, `PlanID`, `Kullanici`, `Islem`(≤100), `Zaman` – işlem günlüğü |
| `spKilit` | `ID`=1, `Surum` – global SPS yazma kilidi |
| `sp157SalonAyar` | PK(`MekanID`), `Kapasite`, `Uyruk` – salonun kalıcı varsayılanı (sonraki planlara taşınır) |
| `sp157SalonSec` | PK(`SinavID`,`SalonID`), `Dahil` – sınav bazında izinli salon listesi |

**Roller** (`S157RolForm` ~19291): `"A"` = **Salon amiri** (Heyet raporunda "Amir"), `"G"` = **Gözetmen**, `"T"` = **Taşıyıcı**.

**Sınav türleri** (`S133Tur` ~10958, tam literal): `"%100 MT"`, `"%100 ÇS"`, `"%40 MT + %60 UYG"`, `"%100 UYG"`. Türünde `"UYG"` geçenler **uygulamalı** sayılır (`S133Uyg` ~10664).

#### 3.2.2 Yetki, kilit, sürüm, günlük

- Yetki (`S133Yetki` ~10647): yönetici oturumu (`P126Yetki`) + (P143 varsa) `A143Izin("SPS")`. Bölüm hesapları SPS'e erişemez.
- Her yazma `S133DB` (~10683) ile: ayrı workspace + transaction → `pp151Kilit.Surum+1` → `spKilit.Surum+1` (yönetici hâlâ geçerli koşuluyla) → plan için **iyimser kilit** `UPDATE spPlan SET Surum=Surum+1 WHERE PlanID=? AND Surum=<ekrandaki> AND Durum='Taslak'` (kesinleştirme/rapor hariç). Etkilenen ≠1 → "Plan değişmiş veya kesinleşmiş". Kesin plan değiştirilemez; önce geri alınmalı.
- Bitiş `S133Bitir` (~10711): yetki tekrar kontrol, `spGunluk`'a işlem metni, commit. Hata → rollback (`S133Geri`).
- STS değişim damgası `S10Stamp` (~7391): tüm `stDonem.Surum` + `spKilit.Surum` birleşimi. Dağıtım öncesi/sonrası farklıysa işlem geri alınır ("Görev dağıtılırken STS verileri değişti").

#### 3.2.3 Plan yaşam döngüsü

1. **Yeni plan** (`S133Yeni` ~10765): SMS dönemi + STS Z referans dönemi + günlük sınır (≥0) + ad. `Durum='Taslak'`, `Surum=1`. 1.57: `sp157SalonAyar`'daki aktif mekanlar otomatik salon olarak eklenir (`S157SalonHazirla` ~18684).
2. **Veri aktarımı** (Excel, bkz. 3.2.4) veya 1.57 seans takvimi / salon tanımları.
3. **Seans/salon planla** (`S133Calistir(1)` ~11388): taslak yerleşim ve görevler silinir (`S133TaslakSil`) → `S133Takvim` → `S133SalonDagit` → `S133Ihtiyac` → `S133Kontrol`.
   - 1.56 "Planı hazırla" (`S156Hazirla` ~18540): hiç yerleşim yoksa takvim+salon; varsa yalnız salonsuz öğrenciler yerleştirilir (1.57); sonra ihtiyaç + otomatik görev dağıtımı + kontrol. **Mevcut yerleşim ve manuel görevler korunur.**
4. **Görevli dağıt** (`S133Calistir(2)`): ihtiyaç → `S153Dagit` → kontrol.
5. **Manuel düzenleme / değişiklik / takas** (3.2.9).
6. **Kontrol et** (`S133Calistir(3)` → `S133Kontrol`).
7. **Kesinleştir / STS'ye işle** (`S133Kesin(False)`), **geri al** (`S133Kesin(True)`).
8. **Taslak planı sil** (`S133PlanSil` ~11844): onay için `"SIL"` yazılmalı; tüm plan verisi ve günlüğü silinir. (Kesin plan `S133DB` koşulu nedeniyle silinemez.)

Durum literal'leri: `'Taslak'`, `'Kesin'`.

#### 3.2.4 Excel içe aktarma formatı (`S133Sablon` ~10993, `S133Aktar` ~11034)

Şablon sayfaları (başlıklar birebir kontrol edilir, `S133BaslikKontrol`):

| Sayfa | Sütunlar |
|---|---|
| `OgrenciSinavlari` | `Öğrenci No`, `Sınıf`, `Kısım`, `Adı soyadı`, `Uyruk`, `Ders Kodu`, `Ders Adı`, `Sınav Türü` – her satır bir öğrenci×sınav |
| `Seanslar` | `Başlangıç`, `Bitiş` (Excel tarih-saat) |
| `Salonlar` | `Salon adı`, `Sınav kapasitesi`, `Uyruk kuralı`, `Uygulama salonu` (`EVET`/`HAYIR`) |
| `SalonRehberi` | aktif `dpMekan.Ad` listesi (bilgi) |
| `Aciklama` | kullanım notları |

Doğrulamalar: formül yasak; hücre boş/uzun olamaz; en çok 100.000 veri satırı; `Öğrenci No` metin olmalı (baştaki sıfırlar); `Sınıf` ∈ {`1`,`2`}; tür 4 değerden biri (boşluk/büyük-küçük harf normalize); aynı öğrencinin kimlik alanları satırlar arasında aynı olmalı; aynı `Kod`+`Tur` için ders adı aynı olmalı; aynı öğrenci-sınav iki kez → PK hatası. Seans: aynı gün içinde, `bas<bit`, SMS dönem aralığında, tarih `smGun`'da var, seanslar çakışmaz. Salon: `dpMekan`'da aktif ve ad tekil; kapasite >0.

Aktarım ayrı iki düğmedir (öğrenci / seans-salon); **her aktarım ilgili listeyi tamamen değiştirir** ve taslak yerleşim, görev, ihtiyaç, `sp157SalonSec` kayıtlarını temizler.

1.57 alternatifi – seans takvimi üretimi (`S157Seanslar` ~18653, `S157SeansKaydet` ~18840): tarih aralığı (≤366 gün, SMS dönemi içinde) + haftanın günleri (1=Pzt…7=Paz) + saat listesi `"09:00-10:30;11:00-12:00"` (sıralı, çakışmasız, günde ≤24). Plan seansları kullanılıyorsa (sınava seans atanmış veya görev var) takvim değiştirilemez; her tarih `smGun`'da olmalı.

(`U158*` DDS/ÜYBS ders programı aktarımıdır, sınav modülü değildir; `U159*` form boyutlandırma yardımcısıdır – kapsam dışı.)

#### 3.2.5 Seans yerleştirme (`S133Takvim` ~11127)

- Sınavlar öğrenci sayısına göre **azalan** sıralanır.
- Kısıtlar (öğrenci bazında): aynı seansta başka sınavı yok; **başka planlardaki** zamanla çakışan sınavları da dolu sayılır; günlük sınav sayısı < `cap` (`cap = spPlan.Gunluk`, 0 ise o günün seans sayısı; diğer planlardaki aynı gün sınavları da sayılır).
- Uygun seanslar arasından o ana kadar **en az öğrenci yüklenmiş** seans seçilir (eşitlikte kronolojik ilk).
- 8 deneme: her denemede başlangıç sınavı bir kaydırılarak (`(ix+attempt) Mod n`) aynı açgözlü işlem; en çok sınavı yerleştiren deneme seçilir, hepsi yerleşirse durur.
- Yerleşemeyen sınav `SeansID=Null` kalır → kontrol mesajı "Seans bulunamadı: …".

#### 3.2.6 Salon yerleştirme ve uyruk kuralı

**Uyruk kuralı** (`S157Uyruk` ~18779, 1.57 aktifken; değilse `S133Uyum` ~10800):
- `"*"` → herkes.
- `|` ile ayrılmış belirteçler; büyük/küçük harf duyarsız tam eşleşme.
- `"TC"` / `"T.C."` (nokta ve boşluk atılıp `TC`) → yalnız T.C. uyruklu.
- `"MAP"` → **T.C. dışındaki** tüm uyruklar (boş uyruk hariç).
- Öğrencinin uyruğu boşsa yalnız `"*"` eşleşir.
- (Eski `S133Uyum`: yalnız `"*"` ve tam metin eşleşmesi; `TC`/`MAP` normalizasyonu yok.)

**1.57 algoritması** (`S157SalonDagit` ~18700) – şu an etkin olan:
- Plan salonlarından mekânı aktif olanlar; her seans için **başka planın çakışan seansında kullanılmayan** salonlar (`S133SalonBos` ~10851); mevcut doluluklar sayılır (yalnız salonsuz öğrenciler yerleştirilir, mevcut yerleşim korunur).
- Her salonsuz öğrenci×sınav için uygun salon kümesi: sınavın `sp157SalonSec` listesi varsa yalnız `Dahil=True` salonlar; uyruk kuralı sağlanmalı.
- **En kısıtlı öğrenci önce** (uygun salon sayısı az olan; eşitlikte giriş sırası – kararlı ekleme sıralaması).
- Kapasitesi dolmamış uygun salonlardan **en az dolu olan** seçilir (dengeli dağıtım; eşitlikte SalonID sırası). Uygun yoksa salonsuz kalır.
- `Istisna=False` yazılır.
- Not: bu sürümde UYG sınavları ve `Manuel` (uygulama) salonları **filtrelenmez** (bkz. açık sorular).

**Eski algoritma** (`S133SalonDagit` ~11214, 1.57 yokken): yalnız `Manuel=False` salonlar ve `Tur`'unda UYG olmayan sınavlar; uyruk grupları "uygun salon sayısı en az olan" sırayla; salon maliyeti: kısıtlı uyruk kurallı salon (−1e9) > zaten kullanılan salon (−1e6) > büyük kapasite → salonları **doldurma** eğilimli.

**Sınav-salon izni** (`S157SalonListe` ~18966, `S157SalonTik` ~18988): sınav için liste ilk açıldığında tüm plan salonları `Dahil=True` eklenir; sonradan eklenen salonlar `Dahil=False`. İçinde o sınavın öğrencisi olan salon kapatılamaz. Hiç kaydı olmayan sınav tüm salonlara açıktır (`S157Izin` ~18679).

**Kalıcı salon ayarı** (`S157SalonKaydet` ~18927): kapasite/uyruk değişikliği mevcut yerleşimle çelişirse (seans başına öğrenci > yeni kapasite, istisnasız öğrenci kurala uymuyor) reddedilir; `sp157SalonAyar`'a yazılır ve sonraki planlara taşınır.

**Uygulama salonu** (`S154Ekle` ~17954): yalnız taslak plana, plana eklenmemiş aktif mekân, `Manuel=True`. Mevcut normal salon dönüştürülmez. Öğrenci ve görevli **manuel** atanır.

#### 3.2.7 Görevli ihtiyacı (`S133Oneri` ~10809, `S133Ihtiyac` ~10818)

Her (seans, salon) için yerleştirilmiş öğrenci sayısı `N` üzerinden:

| Rol | Kural |
|---|---|
| `"A"` (salon amiri) | `N >= 40` ise 1, değilse 0 |
| `"T"` (taşıyıcı) | `N > 0` ise 1 |
| `"G"` (gözetmen) | `N < 40` ise 1; aksi halde `(N + 19) \ 20` (= ⌈N/20⌉) |

- `Ozel=True` satırlar (yönetici elle belirlemiş, `S133ManuelYaz(3)` ~11686) yeniden hesaplamada korunur; `Ozel=False` olanlar her seferinde sıfırlanıp yeniden yazılır (öğrencisi kalmayan salonda 0).
- Uygulama salonlarında ihtiyaç kaydı oluşur ama otomatik dağıtım bu salonları atlar (manuel doldurulur).

#### 3.2.8 Görevli dağıtım algoritması (ayrıntılı)

Giriş noktası `S133GorevDagit` (~11336) → `S153Dagit` (~17678).

**A. Ön hazırlık**
1. `S152Kontrol(…, durdur=True, sadeceManuel=True)`: korunacak manuel görevler kurallara uymuyorsa işlem durur.
2. Plandaki **otomatik** görevler silinir (`Manuel=False`); manuel görevler korunur.
3. Aday skorları `S133Skorlar` (B), müsaitlik havuzu `S133Havuz` (C), dinlenme bağlamı `S152Baglam` (D) kurulur.
4. İş listesi: `spIhtiyac` × salon × seans; 1.57'de içinde UYG sınav öğrencisi olan (seans,salon) çiftleri, öncesinde `spSalon.Manuel=True` salonlar **hariç**. Her iş için `kalan = Sayi − mevcut(manuel) görev sayısı`; `kalan>0` olanlar `(SeansID, SalonID, Rol, Baslangic, Bitis, kalan)` olarak sıralanır: `ORDER BY Baslangic, Rol, SalonID, SeansID`.

**B. Aday skoru – `S133Skorlar` (~11273)**
- Z istatistiği: plan `ReferansID` dönemindeki `stKayit` satırlarından `Katil=True` olanların `DersSaat` değerleri; ortalama ve **popülasyon** standart sapması (Welford, `S10IstatistikEkle` ~7401; `ss = Sqr(m2/n)`). `Katil=True` kimse yoksa veya `DersSaat` null/negatifse hata.
- Adaylar: `spRol`'de rolü olan tüm personel. Her biri için:
  - Z referansında `stKayit` yoksa → aday dışı. `Katil=True` ise `ders = DersSaat` (null → aday dışı); `Katil=False` ise `ders = ortalama` (z=0).
  - Plan döneminin `IlkGun` yılı ile **aynı takvim yılındaki tüm STS dönemlerinde** (`stDonem`) `stKayit.HaftaIci/HaftaSonu` dolu olmalı; toplanır (`hi`, `hs`). Eksik/null → aday dışı ("…görev sayıları veya Z referans kaydı eksik. Sıfır görev için 0 girin." → `spSorun`).
  - Aynı yıldaki **kesin** SPS planlarının `spAktar` katkısı eklenir (`S133STSEkle` ~10857, `tur=1`).
  - Temel skor (`S10Skor` ~7408): **`skor = hi + 1,5 × hs + z`**, `z = (ders − ort) / ss` (`ss=0` ise `z=0`).
  - Aynı yıldaki **taslak** planlardaki mevcut görevler (bu planın manuel görevleri dahil; otomatikler az önce silindi): hafta içi `+1`, hafta sonu (`Weekday(…,2)>5`, Cumartesi/Pazar) `+1,5`; bu plandakilerin adedi `n`, hafta sonu adedi `hs`'ye eklenir.
  - Sonuç dizisi: `(Rol, skor, n, hs, Rnd())`.
- Yorum: geçmiş görevi az ve **haftalık ders saati düşük** olan (z negatif) kişinin skoru düşüktür ve önce seçilir; ders yükü yüksek olan daha az görev alır.

**C. Müsaitlik havuzu – `S133Havuz` (~11340), `S133HavuzMusait` (~11370)**
- `"B|pid"`: o SMS dönemi için `smBildirim` var **ve** (P151) kapsamda `Dahil=True`. Bildirimi olmayan aday hiç atanamaz.
- `"M|pid|yyyymmdd"`: o günün `OO`/`OS` bayrakları. Kural:
  - `OO=True` ve seans **12:00'den önce başlıyorsa** → uygun değil.
  - `OS=True` ve seans **12:00'den sonra bitiyorsa** → uygun değil. (Öğleni kesen seansı iki bayrak da engeller.)
- `"J|pid"`: kişinin **tüm planlardaki** görev zaman aralıkları; `[bas,bit)` çakışması → uygun değil.
- Aynı kural SQL olarak `S133Musait` (~10839) içinde de vardır (manuel atama ve kontrol için).

**D. Dinlenme / yük kuralları – `S152Engel` (~17306)**
Plan alanları (0 = kapalı, 0–1000): `DinGunluk` (bir günde en fazla görev), `DinArdisik` (art arda en fazla görev), `DinAra` (iki görev arasında en az boş seans), `GorevSiniri` (bu planda kişi başı en fazla görev). Seans "sırası" = o gün içindeki plan seanslarının kronolojik sıra numarası (`S152Baglam` ~17331; dakika değil). Kurallar yalnız **bu plan** içinde uygulanır. İlk engel döner (literal):
1. `GorevSiniri>0` ve mevcut görev sayısı ≥ sınır → `"Plan görev üst sınırı"`
2. Aynı gün aynı sıra → `"Aynı seans"`
3. `DinAra>0` ve |sıra farkı| ≤ `DinAra` → `"Boş seans aralığı"`
4. `DinGunluk>0` ve o günkü görev ≥ sınır → `"Günlük görev üst sınırı"`
5. `DinArdisik>0` ve ardışık sıra zinciri > sınır → `"Art arda görev üst sınırı"`

**E. Uygunluk – `S153Uygun` (~17603)**: aday rolü = iş rolü **ve** havuzda müsait **ve** `S152Engel` boş.

**F. Karşılaştırma – `S153DahaIyi` (~17612)**: sözlük sırası, küçük olan iyi: (1) `skor`, (2) bu plandaki görev sayısı `n`, (3) hafta sonu görev sayısı `hs`, (4) rastgele sayı (`Randomize` ile; **deterministik değil**).

**G. Deneme – `S153Dene` (~17620)** (aday/havuz/kural sözlüklerinin bağımsız kopyaları üzerinde):
- İş sırası: deneme 1 = tarih sırası; deneme 2 = "dar önce": her işin `uygun aday sayısı / kalan ihtiyaç` oranı küçükten büyüğe (kararlı ekleme sıralaması).
- Her iş için `kalan` kadar tekrar: en iyi uygun aday seçilir; yoksa o işin kalanı boş bırakılır. Seçilince aday güncellenir: skor `+1` (hafta içi) / `+1,5` (hafta sonu), `n+1`, hafta sonuysa `hs+1`; havuza görev aralığı, kural bağlamına seans eklenir. Kayda **atama anındaki skor** (`AtamaSkoru`, artıştan önceki değer) yazılır.
- Maliyet = tüm adayların son skorlarının **kareleri toplamı** (dengeli yük).
- Seçim: daha çok görev dolduran; eşitse maliyeti düşük olan.

**H. Onarım – `S156Onar` (~18487)**: seçilen sonucta eksik kalan her iş için (toplam en çok 500 deneme): önce doğrudan uygun aday aranır; yoksa aynı roldeki mevcut her otomatik atama için "o kişiyi bu işe kaydır, onun eski işine başka uygun aday bul" (tek adımlı artıran yol) denenir. Son durum sıfırdan yeniden kurulup doğrulanır (`S156Kur`: ihtiyaçtan fazla atama, tanımsız aday, kural ihlali → hata).

**I. Yazma**: kazanan otomatik görevler `spGorev(Manuel=False, AtamaSkoru)` olarak eklenir → `S152Kontrol(durdur=True)` → `spGunluk`'a özet: `"1.56: tarih=<n1>, dar=<n2>, onarim=<önce>-><sonra>, arama=<deneme>"`.

Rapor notu (kodda açıkça): "Sistem kısıtları koruyan sezgisel bir taslak üretir; matematiksel en iyi yerleşim garantisi vermez." (~11788)

`S152YenidenDagit` (~17458): yeni kuralları kaydeder, manuel görevleri doğrular, yalnız otomatik görevleri yeniden dağıtır; öğrenci/seans/salon korunur.

#### 3.2.9 Manuel işlemler

- **Öğrenci yerleştir** (`S133ManuelYaz(1)` ~11656): sınav kendi seansında olmalı; salon aktif, plana ait, başka planda çakışan kullanımda değil; (1.57) salon sınava izinli; (1.57 öncesi) UYG sınav ↔ uygulama salonu eşleşmesi zorunlu. Tek öğrenci veya sınavın tüm öğrencileri. Uyruk kuralına uymayan öğrenci yalnız **İstisna** işaretiyle ve onayla yerleşir → `Istisna=True` (kurala uyuyorsa `False`). Kapasite aşılırsa tüm işlem geri alınır.
- **Toplu taşıma** (`S157Tasi` ~19117, `S157OgrTasi`): seçili öğrenci×sınav satırları hedef salona; uyruk kuralı zorunlu (**istisna yok**), sınav-salon izni, salon çakışması, seans bazlı kapasite kontrolü; `Istisna=False`.
- **Görevli ekle** (`S133ManuelYaz(2)`): `S152AtaKontrol` (dinlenme kuralları), `S133Musait` (bildirim, mazeret, çakışma), kişinin `spRol`'ü olmalı, salonda o seansta öğrenci olmalı; rol `spRol`'den alınır; `Manuel=True`. (Rol ihtiyacı aşılsa bile eklenebilir; kontrol uyarı verir.)
- **İhtiyaç sayısını değiştir** (`S133ManuelYaz(3)`): rol ∈ {A,G,T}, sayı ≥0 → `Ozel=True`.
- **Görev sil** (`S133GorevSil` ~11702).
- **Personel değiştir / iki görevi takas et** (`S155*` ~18041–18364): yalnız taslak plan ve ekrandaki `Surum` güncel; zorunlu açıklama 1–200 karakter; önizleme (eski/yeni kişi, bu plandaki görev ve puan değişimi) + **imza** (sürüm+model+özet) – uygulamada imza aynı değilse reddedilir. Uygunluk `S153Neden` sırasıyla (rol aynı olmalı). Değişen görevler aynı `GorevID` ile `Manuel=True`, `AtamaSkoru=Null` yazılır; günlüğe `"D155 R<sürüm> #<parça> …"` parçalı metin.
- **Rol tanımları** (`S133RolKaydet` / `S157RolKaydet` ~19233): toplu atama/kaldırma, satır başına `Surum` iyimser kontrol; mevcut planların görevleri otomatik değişmez.

#### 3.2.10 Kontrol / sorun tespiti (`S133Kontrol` ~11433)

Her çalıştırmada `spSorun` temizlenip yeniden üretilir (dağıtım sonrası çağrıda temizlemeden ekler). Kontroller:
- Öğrenci sınav kaydı yok.
- Seansı olmayan sınav ("Seans bulunamadı: kod / tür …").
- Salonsuz öğrenciler (UYG ise "Uygulama salonunu manuel atayın").
- Öğrencinin aynı seansta birden fazla sınavı; günlük sınav sınırı aşımı (diğer planlar dahil); başka planda çakışan sınavı.
- Salon kapasitesi / mekân aktifliği / plan uyumu; salonun başka planda çakışan kullanımı.
- Uyruk kuralına aykırı ve `Istisna=False` yerleşim; (1.57 öncesi) uygulama/normal salon ayrımı.
- Seans `smGun`'da değil; seans süresi/tarih aralığı geçersiz; plan seansları çakışıyor.
- Her (seans,salon,rol) için atanan ≠ `Sayi` → "Görevli sayısı: <salon> / Seans <id> / <rol> gereken X, atanan Y…".
- Her görev için: `S133Musait` değil; `spRol` rolü uyuşmuyor; ihtiyaç kaydı yok; boş salona görev; **hedef STS döneminde** (`DonemID`) kişinin `stKayit.HaftaIci/HaftaSonu` dolu değil.
- `S152Kontrol` (dinlenme kuralları), 1.57 `S157EkKontrol` (sınava kapalı salonda öğrenci).
- Dönüş = `spSorun` sayısı.

#### 3.2.11 Kesinleştirme ve STS aktarımı (`S133Kesin` ~10876)

- Onay ekranında hafta içi/hafta sonu görev toplamı ve personel sayısı gösterilir.
- **Kesinleştir**: plan zaten `'Kesin'` ise reddedilir; `S133Kontrol` çalışır, **`spSorun` boş değilse kesinleşmez**; plan dönemi STS'de açılmış olmalı (`stDonem` kaydı); `spAktar`'a kişi başına `HaftaIci = Count(Weekday(Baslangic,2)<=5)`, `HaftaSonu = Count(>5)` (manuel + otomatik tüm görevler) → `Durum='Kesin'`.
- **Geri al**: `spAktar` silinir, `Durum='Taslak'`.
- Her iki durumda `stDonem.Surum+1` (STS taslaklarını ve dağıtım damgalarını geçersiz kılar), `spGunluk` kaydı.
- Puan kuralı (rapor metni ~11787): "Her seans ayrı görev. Hafta içi +1, hafta sonu +1,5. Manuel görevler dahildir."

#### 3.2.12 Raporlar (`S133Rapor` ~11771, `S153Rapor` ~17764, `S157UcRapor` ~19342)

Excel sayfaları: Plan bilgisi; Personel görev kuralları; Genel sınav planı; Öğrenci programları; Salon öğrenci listeleri (uyruk istisnası sütunu ile); Personel görevleri (görev puanı 1/1,5 ve "Atama öncesi geçici skor"); Personel görev dengesi (manuel/otomatik, hafta içi/sonu, plan puanı, rol grubu ortalaması, aday durumu); Boş görev nedenleri (nedenler kategorileri: rol havuzu, kapsam dışı, bildirim yok, STS eksik, mazeret, çakışma, görev/dinlenme sınırı, "Şu anda uygun"); Boş görev adayları; Rapor açıklaması; Kontrol sonuçları; İşlem günlüğü. 1.57 resmi çıktılar: `Ogrenci_Sinav_Plani`, `Sinava_Girecekler`, `Heyet_Carsaf` (6 seanslık bloklar, kişi × seans → salon adı). Planlanmamışlar `"PLANLANMADI"`, salonsuz `"SALON YOK"`. Rapor başlığı `spPlan.RaporBaslik` yoksa kodda sabit kurum başlığı kullanılır.

---

### 3.3 STS – Skor Takip Sistemi (sınav görevi katılımı)

#### 3.3.1 Veri modeli (`STSKur` ~7734)

| Tablo | İçerik |
|---|---|
| `stDonem` | PK `DonemID` (= `smDonem.DonemID`), `Surum` – dönem STS'de "açık" |
| `stKayit` | PK(`DonemID`,`PersonelID`), `Katil` (Z hesabına katılır), `HaftaIci` LONG, `HaftaSonu` LONG, `DersSaat` DOUBLE (haftalık ders saati). Null = "bilinmiyor/eksik"; **0 = görev yok**. |
| `stGunluk` | `ID`, `DonemID`, `PersonelID`, `Surum`, `Katil`, `HaftaIci`, `HaftaSonu`, `DersSaat`, `Kullanici`, `KayitZamani`; UNIQUE(`DonemID`,`PersonelID`,`Surum`) – her kayıtta **tam değer anlık görüntüsü** |

`HaftaIci/HaftaSonu` STS'ye **elle girilen** (SPS dışı) görev sayılarıdır; kesin SPS planları `spAktar` üzerinden rapor/skor anında eklenir (ekran notu "Giris: manuel gorevler | Rapor: manuel + kesinlesen SPS gorevleri", ~7102).

#### 3.3.2 Yetkiler (`S10Yetki` ~7078, `S10OkumaYetki` ~7083)

- **Yazma** (giriş, Excel şablon/aktarım, kaydet): yalnız yönetici (`v4Admin`) + `P7Yetki("STS")`.
- **Okuma** (dönem açma, skor raporu, Excel raporu): STS yetkisi + (yönetici **veya** bölüm hesabı). Bölüm hesabı yalnız kendi bölümünün personelini görür (`S10BolumKosulu` ~7089, `S10RaporSinirla` ~7554); ekran salt okunur.

#### 3.3.3 Giriş ve kayıt

- Dönem açma (`S10Yukle` ~7252): tüm personel (bölüm filtresi hariç kapsam filtresi yok) + mevcut `stKayit` değerleri yerel geçici taslağa alınır; `stDonem.Surum` okunur.
- Doğrulama (`S10DegerKontrol` ~7301): `Katil=True` ise `HaftaIci`, `HaftaSonu`, `DersSaat` üçü de zorunlu; negatif yok; görev sayıları tam sayı.
- Kayıt (`S10Kaydet` ~7340): tek transaction; dönem düzeyinde iyimser kilit (`rev=0` → `INSERT stDonem(Surum=1)`, aksi `UPDATE … Surum=Surum+1 WHERE Surum=<okunan>`); satır bazında upsert `stKayit`; her satır için `stGunluk` anlık görüntüsü; tüm SQL'lerde "yönetici hâlâ geçerli ve `ParolaSurum` aynı" koşulu (`S10Auth` ~7317). "Tümünü kaydet" veya tek satır.

#### 3.3.4 Skor formülü (`S10Skor` ~7408, `S10Rapor` ~7414)

```
Skor = HaftaIci + 1,5 × HaftaSonu + Z
Z    = (DersSaat − Ortalama) / StandartSapma    (StandartSapma = 0 ise Z = 0)
```

- Ortalama ve standart sapma (**N ile**, popülasyon): seçili dönemde (`Z referansı` = seçili dönem) `Katil=True` olanların `DersSaat` değerleri. Hiç yoksa rapor üretilmez.
- `Katil=False` kişi için `DersSaat = Ortalama` (Z=0) alınır; raporda ders saati boş gösterilir.
- **Kapsam** `cmbKapsam`: `0` = "Seçili sınav dönemi" (o dönemin `HaftaIci/HaftaSonu` + o dönemin kesin SPS katkısı); `1` = "Yılın STS kayıtlı dönemleri" (dönemin `IlkGun` takvim yılındaki **tüm** `stDonem` dönemlerinin toplamı – her dönemde kişinin dolu kaydı zorunlu, yoksa hata – + o yılın kesin SPS katkısı).
- **Rapora giren kişiler** (`S133STSPersonelKosulu` ~10918): seçili dönemde `stKayit` satırı olan **ve** (`Katil=True` **veya** kapsamda kesin SPS görevi olan). (Z'ye katılmayan ve SPS görevi olmayan kişi raporda görünmez.)
- **Filtre** `cmbFiltre`: `0` Tümü; `1` `Skor > Alt`; `2` `Alt ≤ Skor ≤ Üst`. Karşılaştırma yuvarlanmamış skorla, gösterim 4 ondalık.
- Sıralama: `Skor` artan, sonra ad. Rapor sırasında `S10Stamp` değişirse veya yetki düşerse iptal.

SPS ilişkisi: SPS aynı formülü kullanır ama Z için **plan `ReferansID` dönemini** ve sayılar için **yıl toplamını** alır; ayrıca taslak plan görevlerini geçici olarak ekler (3.2.8-B).

#### 3.3.5 Excel

- **Şablon** (`S10Sablon` ~7802): `Giris` sayfası sütunları `PersonelID`, `TCKN`, `AdSoyad`, `Bolum`, `ZyeKatil`, `HaftaIciGorev`, `HaftaSonuGorev`, `HaftalikDersSaati`; `Donem` sayfası `DonemID`, `DonemAdi`, `Surum` + kullanım notu.
- **Aktarım** (`S10Aktar` ~7875): başlıklar ilk 11 sütunda aranır (tekrar/eksik → hata); `DonemID` dolu ise açık dönemle aynı olmalı (boşsa onay sorulur); `Surum` dolu ise güncel sürümle aynı olmalı ("Excel eski sürüme ait"); en çok 10.000 satır; formül yasak; eşleştirme **TCKN** ile (PersonelID verilmişse uyuşmalı); aynı kişi iki kez → hata; `ZyeKatil` ∈ {0,1}; değer doğrulaması `S10DegerKontrol`. Aktarım yalnız ekran taslağını günceller; kalıcı kayıt için "Tümünü kaydet" gerekir. Dosyada olmayan kişiler değişmez.
- **Skor raporu** (`S10RaporDosya` ~7986): `Skorlar` (TCKN, Adı soyadı, Bölüm, Hafta içi görev, Hafta sonu görev, Haftalık ders, Z puanı, Skor) + `Hesap Bilgisi` (kapsam, istatistik: öğretmen sayısı/ortalama/SS, dönem listesi, formül, filtre notu, oluşturma zamanı).

#### 3.3.6 Kurulum/menü

`STSKur` tabloları oluşturur, formları yeniden üretir, `STS10Hazir` özelliğini ayarlar; `STSMenuGuncelle` (~7617) yalnız ana menü/kart arayüzünü günceller (iş kuralı yok).

---

## 4. Web'e taşırken dikkat

### 4.1 DDS

**Korunması gereken iş kuralları**
1. Plan sürümleri `Taslak` → `Yayin`; plan **okul geneli** bir haftalık şablondur ve tarih aralığına sahiptir. Yayında tarihli dersler `Gun` (1=Pzt … 7=Paz) eşleşmesiyle, tatiller atlanarak üretilir; 1 satır = 1 DS.
2. "Geçerli ders" kuralı: bir tarih için o tarihi kapsayan, **en geç başlayan** yayımlanmış plan; tatil günleri hariç; kişi/bölüm yalnız `Kesin` devirle değişir (`qDdGuncel`/`qDdSon`). Web'de bu bir queryset/DB view olarak birebir korunmalı (eski satırlar silinmiyor; silinecekse aynı sonuç garanti edilmeli).
3. Yayın engelleri: ilk yayın hariç başlangıç ≥ bugün; başlangıç önceki tüm yayınlardan sonra; tüm slotlar eşlenmiş; aynı kişi aynı gün+saatte tek ders; etkilenen aralıkta açık/kesin devir ve beyan/teyit yok.
4. Devir durum makinesi: `Talep` → `Onay` (yönetici) → `Kesin` (yalnız ana yönetici); `Iade` (Talep/Onay'dan, yönetici); `Iptal` (Kesin'den, yalnız ana yönetici). Her geçişte gerekçe, karar veren ve zaman; geçiş önceki duruma koşullu; onay/kesin/iptal öncesi uygunluk yeniden denetlenir; karar **`BlokGrup`** bütününe uygulanır; ders başına en çok bir etkin devir.
5. Uygunluk: DMS maskesi (Pzt–Cuma, 1–8. saat, `pos=(gün−1)×8+saat`, `'1'`=mazeretli, bildirim yoksa denetim yok) + aynı tarih/saatte son personel çakışması.
6. Beyan/teyit: gelecek tarih yok; teyit beyandan sonra ve yönetici; bekleyen devirde yapılamaz; beyan/teyit dersi dondurur (devir, tatil, yeni yayın engeli).
7. Bölüm hesabı görünürlüğü: asıl **veya** son bölüm; talep yalnız asıl bölüm; beyan yalnız son personelin bölümü.
8. Excel aktarımı: tümü-ya-hiç; formül yasağı; toplam DS sütunu çapraz kontrolü; Biçim B'de DPS'ten tekil ders çözümü; `ddEsleme` ile kalıcı ad eşlemesi.
9. Tüm DDS yazmaları tek bir mantıksal kilit altında sıralı (web'de `select_for_update` ile bir "DDS dönem" satırı kilitlenebilir veya ilgili satırlar kilitlenir).

**Taşınmaması gereken Access geçici çözümleri**
- `ddKilit` sayaç-muteksi (DB transaction + `select_for_update` yeterli), private workspace/`CurrentDb` ayrımı, `D140DT` ABD tarih literali üretimi, `@@IDENTITY` okuma.
- `D140Onizle`'deki 600 karakterlik `MsgBox` sayfalaması → web'de tek bir önizleme/onay sayfası.
- `D1401Iz` tanı günlüğü dosyası, `DDSExcelDosyadan`/`DDSExcelKontrol` (dosya seçme penceresi sorunları için eklenmiş geçici yollar), `%TEMP%` TXT hata listeleri → hata listesi yanıtın parçası olmalı.
- `D143*` form yerleşimi, sekme simülasyonu, ListBox karakter sınırı, `D142Rows` içindeki metin birleştirme (blok, sunucu tarafında gruplanmış veri olarak üretilmeli).
- Excel'in COM ile açılması, `AutomationSecurity` vb. → openpyxl (formül tespiti için `data_only=False` ile okuma gerekir).

**Açık sorular (DDS)**
1. Taslak plan silme / yayından kaldırma işlevi yok; web'de gerekli mi?
2. Yeni plan eski plandan önce biterse eski plan kalan tarihlerde yeniden geçerli oluyor — kasıtlı mı? Yoksa yeni yayın, sonraki tüm tarihleri mi kapatmalı?
3. Beyan/teyit için son tarih, geri alma veya reddetme ihtiyacı var mı? (Kodda yok.)
4. Beyan alanı hesabın kullanıcı adını tutuyor; web'de öğretim elemanları bireysel hesapla mı girecek, beyanı kimin yaptığı nasıl tutulacak?
5. Bekleyen talepler çakışma denetimine dahil edilmeli mi? DMS bildirimi olmayan hedef ve 9+ saatler için de uyarı/engel istenir mi?
6. Tatil silme/düzeltme işlevi yok; gerekli mi?
7. `ddDers.BolumID` yayın anındaki bölümün kopyası; personel bölüm değiştirirse geçmiş/gelecek dersler hangi bölüme sayılmalı?
8. `Mekan` ve `Tur` serbest metin; web'de `dpMekan` FK'si ve `T/U` enum'u kullanılabilir mi? Yayında `Belirsiz`/mekansız slota izin verilmeye devam edilsin mi?
9. Ders saati numarası DDS'te 1–20, DMS ve ÜYBS'te 1–8; gerçek saat tablosu yalnız ÜYBS aktarımında kodda sabit (1.1.17). Web'de saat tablosu ayar olarak mı tutulmalı?
10. DDS program Excel'i (H sütunundan itibaren gün/saat başlıklı) ile ÜYBS kaynak Excel'i (F:AS sabit 40 hücre) farklı düzenler; ikisi aynı üçüncü taraf programın farklı çıktıları mı? Web'de tek bir kaynak biçimi mi desteklenecek?
11. Teyit herhangi bir DDS yetkili yöneticiye, kesinleştirme yalnız ana yöneticiye açık; bu ayrım web rol modelinde aynen mi kalacak?
12. ÜYBS aktarımı (aSc XML karşılaştırması, referans sürümleme) ilk fazda taşınacak mı?

### 4.2 DPS / DMS / BDD

**Korunması gereken kurallar**
1. DS formülleri: `T → Saat = Kisim×(Teorik+Uygulama)`, `U → Saat = Kisim×Uygulama`; kırılım `TeorikDS = Kisim×Teorik (yalnız T)`, `UygulamaDS = Kisim×Uygulama (T ve U)`; `TeorikDS+UygulamaDS = Saat` değişmezi. T/U veya kısım değişince mevcut atamaların `Saat`'i yeniden hesaplanmalı (veya hesaplanan alan yapılmalı).
2. Kapasite: grup (aynı dönem+veren bölüm+sınıf+kod+T+U) için `Σ Kisim(T) ≤ Σ dpDers.Kisim`, `Σ Kisim(U) ≤ Σ dpDers.Kisim`, `Σ Kisim(U) ≤ Σ Kisim(T)`; satır bazında `Σ Kisim(tür) ≤ dpDers.Kisim`. Kısım/T-U değişikliği bu sınırları bozamaz; `Uygulama=0` iken U ataması olamaz.
3. `dpDers.Kisim`, alan bölümün `dpBolumKisim` (`Birinci`/`Ikinci`) değerinden türetilir; kısım ayarı değişince o alan bölüme verilen tüm dersler güncellenir.
4. Sahiplik: planlayan bölüm (`BolumID`) atamaları yapar; ders tanımı/aktarımı yalnız ana yönetici; kısım ayarı yönetici; personel her bölümden atanabilir.
5. Mekan zorunlu ve etkin bir `dpMekan` olmalı; ad `"KOD - Ad"` biçimi; kullanımdaki mekan silinemez, yalnız pasife alınır.
6. DMS maskesi: 40 karakter, `0/1`, `pos=(gün−1)×8+ders`, `1`=mazeretli; boş maske kaydı ≠ kayıt yok. DDS bu maskeyi okuyarak atama engelliyor — biçim birebir korunmalı (veya ayrı tabloya geçilecekse DDS de uyarlanmalı).
7. Giriş penceresi: `GiriseAcik AND (SonBildirim IS NULL OR now <= SonBildirim)`, saniye `:59`, varsayılan saat `23:59`; bildirim alınmış dönemde yıl/no/ilk pazartesi değişmez.
8. Her DMS kaydında tam anlık görüntülü `dmGunluk` (sürüm başına bir satır); iyimser kilit (`Surum`) tüm güncellemelerde.
9. Bölüm hesabı DMS raporunu, tüm bölüm personeli bildirim yapmadan alamaz.
10. BDD: dönem başına personel başına tek branş; ortalama = toplam DS / atanmış personel (0 yük dahil, atanmamışlar hariç); DS tüm bölümlerin DPS yüklerinden.
11. Excel ders aktarımı kuralları (başlık birebir, dönem ID eşleşmesi, tekil bölüm adı, 1/2 sınıf, kod/ad uzunlukları, dosyada olmayan ders silinmez, tümü-ya-hiç transaction).

**Access'e özgü, taşınmaması gereken geçici çözümler**
- `D138Kilit`'teki `UPDATE dmDonem SET DonemNo=DonemNo` sahte kilit ve `dpBolumKisim` `Surum+1` "dokunma"ları → Django'da `select_for_update()` / transaction ile.
- `EXISTS (SELECT * FROM smKullanici … ParolaSurum=…)` yetki koşullarının her SQL'e gömülmesi → oturum/izin katmanı (decorator/permission) ile.
- `qD138*` kayıtlı sorguları ve `GrupID=Min(DersID)` → Django'da gerçek bir "ders grubu" modeli (ör. `Ders` + `DersAlanBolum` alt tablosu) veya annotate'li queryset; GrupID'ye bağımlı olmayın.
- Atamanın alan bölüm satırlarına `DersID` sırasıyla "dağıtılması" yalnız fiziksel modelden kaynaklanıyor; grup düzeyinde tek atama satırı tutmak düşünülebilir (raporlar alan bölüm kırılımı istemiyorsa).
- `D11Damga`/`D138Damga` metin damgaları, `txtRev.Tag` gizli alanları, DMS toplu girişteki geçici `.accdb` taslak dosyası, form kurulum/yedek (`d11_`, `p8_`, `h123_`, `m137_` önekli form kopyaları), `PPYS1xxGuncelle` göç prosedürleri, `DPS11Hazir` vb. özellik bayrakları.
- `dpSinif` tablosu ve `D13Sinir`, `D11Toplam` (ölü kod); `dpAtama.Kisim Is Null` "eski DS" yolları (göçte temizlenip `NOT NULL` yapılmalı).
- `M137Sema`'daki 3 harfli kullanıcı adından bölüm kodu türetme.
- Excel'i COM ile oluşturma, `FileDialog`, `%TEMP%` TXT hata dosyası → sunucu tarafı openpyxl + indirme/yükleme; hata listesi yanıtın parçası.
- ListBox 29.000 karakter önizleme kırpması (`B132ListeYaz`).

**Açık sorular**
1. DMS toplu kayıt, değişmeyen personel için de `Surum+1` ve günlük satırı yazıyor; web'de yalnız değişenler mi yazılsın? (Günlük hacmi ve "son kaydeden" anlamı değişir.)
2. `dpGunluk` silme işleminde kaldırılan kısım/DS'yi kaydetmiyor (`n=0`, `Saat=0`); web'de önceki değer de loglanmalı mı?
3. Ders silme/pasifleştirme işlevi hiç yok; web'de istenecek mi? (Dönem temizliği dışında `dpDers` silinemiyor.)
4. Branş adı düzenleme/silme yok; gerekli mi?
5. BDD yönetici raporu (branşın bölümüne göre) ile bölüm raporu (personelin güncel bölümüne göre) farklı gruplama yapıyor — hangisi doğru kabul edilecek?
6. Personel başına azami haftalık DS sınırı ya da DMS mazereti ile DPS ataması arasında çakışma kontrolü DPS'te **yok** (çakışma kontrolü yalnız DDS'de); web'de eklenecek mi?
7. `dpAtama.Mekan` metin olarak tutuluyor (FK değil); mekan adı değişikliği desteklenmediği için bu tasarım bilinçli mi? Web'de `MekanID` FK'ye geçilmesi önerilir — onay gerekli.
8. Gruplama anahtarının `Teorik`/`Uygulama` içermesi (aynı kodun farklı T/U ile ayrı grup olması) iş kuralı mı yoksa yan etki mi — belirsiz.
9. `0` kısımlı sınıf: ayarda 0 serbest, ama aktarımda kısım <1 hata; 0 kapasiteli ders mümkün mü olmalı — belirsiz.
10. `PersonelKodu` DMS Excel'inde `"T.C.KN"` başlığıyla yazılıyor; web dışa aktarımında bu kimlik numarasının gösterilmesi (KVKK) onaylanmalı.
11. U168/U170 (ÜYBS aktarımı) ve Z150 (DZN) DPS kapsamına alınacak mı, ayrı modül mü — kapsam kararı gerekli.

### 4.3 Sınav modülleri (SMS / SPS / STS)

**Korunması gereken kurallar**
- SMS: dönem başına kişi başı tek bildirim; bildirim tüm dönem günlerini (OO/OS veya tam gün) kapsar; **bildirimsiz kişi SPS'te müsait sayılmaz** ("mazeretim yok" da kaydedilmeli). Durum literal'leri `Bekleniyor` / `Eksik kayit` / `Mazeretli` / `Musait`.
- Dönem yazılabilirliği: `GiriseAcik` + `SonBildirim`; admin istisnası (P151 sonrası) bilinçli bir karar olarak tasarlanmalı.
- Bölüm hesabı yalnız kendi bölümü; SMS kapsamı (`Dahil`); bölüm kesinleştirme (bölüm yapar, yalnız admin kaldırır; kapsam değişince kesinlik düşer; bölüm Excel'i kesinleşmeden alınamaz).
- OO/OS → seans eşlemesi: OO = 12:00'den önce başlayan, OS = 12:00'den sonra biten seansları engeller.
- SPS: dönem başına tek plan; `Taslak`/`Kesin`; kesin plan değiştirilemez; kesinleştirme yalnız kontrol listesi boşken; kesinleştirme/geri alma `spAktar` ile STS'ye yansır.
- İhtiyaç formülü (A: N≥40 → 1; T: 1; G: N<40 → 1, aksi ⌈N/20⌉), `Ozel` override.
- Uyruk kuralı semantiği (`*`, `TC`, `MAP`, `|`), İstisna onayı, sınav-salon izin listesi, salonun başka planla çakışmaması, kapasite.
- Dağıtım: skor = hafta içi + 1,5×hafta sonu + Z (Z ders saatinden, popülasyon SS); taslak görev eklemeleri (+1/+1,5); seçim sırası (skor, plandaki görev, hafta sonu, rastgele); iki deneme + kareler toplamı + onarım; dinlenme kuralları (seans sırası tabanlı); manuel görevlerin korunması; `AtamaSkoru` saklanması.
- STS: Null ≠ 0 ayrımı; `Katil` hem Z istatistiğine hem rapor kapsamına etkili; yıl kapsamında tüm dönem kayıtlarının zorunluluğu.
- Eşzamanlılık: `Surum` tabanlı iyimser kilitler (bildirim, plan, rol, STS dönemi, seçenek) ve tüm-işlem transaction'ları; dağıtım sırasında STS değişimi tespiti (`S10Stamp`) – Django'da `select_for_update`/versiyon alanı ile karşılanmalı.
- Denetim: `smGunluk` (yalnız kim/ne zaman/sürüm), `stGunluk` (tam anlık görüntü), `spGunluk` (metin), `pp151Gunluk`. Web'de SMS için de içerik anlık görüntüsü tutulması önerilir.

**Taşınmaması gereken Access'e özgü çözümler**
- Form/kontrol üretimi (`CreateForm`, `CreateControl`), `PPYSxxxGuncelle` kurulum/yükseltme yordamları, form yedekleme/geri yükleme, `CurrentDb.Properties("…Hazir")` sürüm bayrakları (1.51–1.57 katmanları tek modelde birleştirilmeli; eski `S133SalonDagit`/`S133Uyum` dalları gereksiz).
- `smV6Taslak`/`smV6Matris` + `OturumID`; STS'nin `%TEMP%` altında geçici `.accdb` taslağı; `pp151Kilit`/`spKilit` global sayaç kilitleri (DB transaction + satır kilidi yeter).
- `Scripting.Dictionary`, Excel COM otomasyonu (openpyxl/pandas ile yeniden yazılmalı), `FileDialog`, `InputBox` onayları (`"SIL"` yazma vb.), 62 sütunlu `GxxO/GxxS` matris tablosu, ListBox 28.000 karakter sınırı, `S135Alan` alan adı çözücüsü, `U159*` form ölçekleme.
- Parola: `Tuz`/`Parola`/`ParolaSurum` alanları ayrı tutulmamalı; Django auth'a geçilmeli. Mevcut özetlerin taşınıp ilk girişte yükseltilmesi veya parola sıfırlatılması seçenekleri için bkz. 2.2.

**Açık sorular / belirsizlikler**
- SMS dönem günlerini sonradan düzenleme işlevi kodda yok, ancak SPS mesajları buna atıf yapıyor – web'de gerekli mi? Hafta sonları da otomatik ekleniyor; istenen bu mu?
- Admin'in kapalı/süresi geçmiş dönemde ve kesinleşmiş bölümde yazabilmesi kasıtlı mı, yetki ayrımı (ana admin / yönetici) nasıl olmalı?
- 1.57 `S157SalonDagit` UYG sınavlarını ve `Manuel` (uygulama) salonlarını filtrelemiyor; normal öğrenciler uygulama salonuna, UYG öğrencileri normal salona otomatik yerleşebilir; buna karşın otomatik görev dağıtımı UYG içeren salonları atlıyor. Kasıtlı mı, hata mı? (belirsiz)
- Skorda **rastgele** eşitlik bozma (`Rnd`) sonuçları tekrarlanamaz yapıyor; web'de tohumlu/deterministik olmalı mı?
- `S133Skorlar` yıl tanımı takvim yılı (`Year(IlkGun)`); akademik yıl mı olmalı?
- STS raporunda `Katil=False` ve SPS görevi olmayan kişilerin hariç tutulması bilinçli mi?
- Rol kişi başına tek ve plan bağımsız; plan bazında farklı rol ihtiyacı olabilir mi?
- `spSorun` bilgi mesajı ("Aktarım tamamlandı…") hata listesine yazılıyor; web'de bilgi/uyarı/hata ayrımı yapılmalı.
- Görev puanı haftasonu tanımı `Weekday(…,2)>5` (Cumartesi, Pazar); resmi tatiller dikkate alınmıyor.
- Kurum rapor başlığı kodda sabit; ayarlanabilir olmalı.
- Excel çıktılarında TCKN tam olarak yer alıyor (KVKK açısından maskeleme/erişim değerlendirilmeli).

### 4.4 Platform

**Korunması gereken**
- Üç düzeyli rol modeli (bölüm hesabı / modül yetkili yönetici / tek ana yönetici) ve modül bazlı erişim (`ppModul` bölümler için genel anahtar, `ppYoneticiModul` yönetici başına).
- Hesap pasifleştirme (`HesapAktif`), hesap değişince oturumların düşmesi (`ParolaSurum` → Django'da oturum doğrulama özetini değiştirmek / kullanıcı başına sürüm alanı).
- Parola özetleriyle geriye dönük uyum (2.2; özel hasher + yükseltme).
- Kimlik doğrulamada genel hata mesajı; yetkinin her yazmada sunucu tarafında yeniden denetlenmesi.
- İyimser kilit (`Surum`) semantiği ve "başka kullanıcı değiştirdi" kullanıcı deneyimi.
- Yönetici yetki değişikliklerinin denetim kaydı (`ppYetkiGunluk`).
- "Bakım modu" ihtiyacı varsa: basit bir bayrak + yeni girişleri engelleme (ana yönetici hariç) yeterli.

**Taşınmaması gereken**
- Programatik form üretimi (`CreateForm`/`CreateControl`, `P7Ikon0..5`, `V50*`/`V51*` tasarım, `U159`/`U160`/`U163` ölçekleme/tema), `PPYS1xxGuncelle`/`*Kur` kurulum yordamları, `CurrentDb.Properties("…Hazir")` bayrakları, zaman damgalı form yedekleri.
- 10 saniyelik istemci nabzı (`B144Tik`, `ppBakimIstemci`), geri sayım uyarısı, `TerminateProcess` ile zorla kapatma, özel kipte dosya açma denemesi — web'de sunucu tarafı oturumlar ve dağıtım süreçleri bu ihtiyacı ortadan kaldırır.
- PowerShell ile yedek/geri dönüş ve `.ppys-bakim.json` işaret dosyası → veritabanı düzeyinde yedekleme (pg_dump vb.).
- Yerel taslak tabloları (`smV6Taslak`, `smV6Matris`, geçici `.accdb` dosyaları) ve `OturumID` ayrımı.
- Tek satırlık `*Kilit` tabloları (gerekirse `select_for_update` ile ilgili üst kayıt kilitlenir).
- Her SQL'e gömülü `EXISTS (SELECT * FROM smKullanici …)` yetki koşulu → izin katmanı (decorator / DRF permission) + transaction içinde kullanıcı nesnesinin yeniden okunması.
- `P147*` tanı izleme (`P147Iz`), `PPYSDurumOku` (Module1) gibi teşhis yordamları.
- Kodda sabit kullanıcı adı yazan göç adımları (`V49Guncelle` ~2311, `V5210Guncelle` ~3631) — web'e kesinlikle taşınmamalı; ilk ana yönetici kurulum komutuyla oluşturulmalı.

**Açık sorular (platform)**
1. Parola politikası (en az 6 karakter) ve hatalı giriş sınırlaması yok; web'de güçlendirilecek mi? Kurumsal SSO/LDAP var mı?
2. Öğretim elemanları bireysel hesap alacak mı, yoksa bölüm hesabı modeli mi sürecek? (DDS beyanı, DMS/SMS bildirimleri bu karara bağlı.)
3. Tek ana yönetici kısıtı (benzersiz indeks) web'de de korunacak mı, yoksa "süper yönetici" grubu mu olacak?
4. Yöneticinin `BolumID`'si ("bağlı olduğu bölüm") hiçbir yetkiyi etkilemiyor gibi görünüyor — yalnız bilgi amaçlı mı? (**belirsiz**)

### 4.5 Genel öneriler

- Tüm modüllerde ortak: Excel içe/dışa aktarımları sunucu tarafında, tümü-ya-hiç transaction ile; hata listeleri satır numaralı olarak kullanıcıya dönmeli.
- Excel çıktılarında T.C. kimlik numarası (`PersonelKodu`, "T.C.KN" başlığı) yer alıyor; KVKK açısından erişim/maskeleme kararı verilmeli.
- Kodda okuyan ekranı olmayan günlükler (`dpGunluk`, `ddGunluk`, `ppYetkiGunluk` …) web'de tek bir denetim izi modeline (ör. `django-simple-history` veya ortak `AuditLog`) toplanabilir; ancak `dmGunluk`/`stGunluk`'teki "tam anlık görüntü" semantiği korunmalı.
