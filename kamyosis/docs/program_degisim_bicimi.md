# KAMYOSİS Program Değişim Biçimi — sürüm 1

Bu belge, bir ders programı uygulamasının haftalık ders programını **KAMYOSİS**'e (Kara Astsubay Meslek Yüksekokulu yönetim bilgi sistemi) aktarmak için üretmesi gereken veriyi tarif eder.

- **Biçim:** tek bir JSON dosyası, UTF-8.
- **Şema dosyası:** `program_degisim_bicimi.schema.json` (JSON Schema 2020-12).
- **Örnek dosya:** `ornek_program.json`.

KAMYOSİS bu dosyayı **taslak program sürümü** olarak alır. Yetkili kişi kontrol edip geçerlilik tarihiyle yayınlar. Program ne kadar sık yeniden gönderilirse gönderilsin, KAMYOSİS'teki ders takibi (yapılan dersler, devir) bozulmaz.

---

## 1. Genel kurallar

| Kural | Açıklama |
|---|---|
| Kodlama | UTF-8. Türkçe harfler olduğu gibi yazılır (`BİL103`, `İŞL299`, `UÇT215`). Ders ve kısım kodlarındaki noktalı **İ** önemlidir. |
| Kimlikler (`id`) | Her kayıt, metin türünde bir kimlik taşır. **Aynı kayıt sonraki dışa aktarımlarda da aynı kimliği taşımalıdır.** Kimlikler sadece dosya içi bağlantı ve yeniden yüklemede eşleştirme içindir; anlamlı olmaları gerekmez (UUID, veritabanı numarası vb. olabilir). |
| Kodlar | Ders kodları (`BİL103`), kısım kodları (`1SVN`) ve derslik adları **okulun aSc programındakiyle aynı** yazılmalıdır. KAMYOSİS bölümü bu kodların önekinden bulur (`BİL103` → Bilgisayar Teknolojisi, `1SVN` → Savunma Hizmetleri). |
| Gün | ISO hafta günü: 1 = Pazartesi … 5 = Cuma, 6 = Cumartesi, 7 = Pazar. |
| Saat | Ders saati sırası (`ders_saatleri[].no`), saat değeri değil. 1. ders, 2. ders… |
| Yerleşim | **Her yerleşim kaydı tek bir ders saatidir.** İki saatlik blok ders iki kayıt olarak yazılır. |
| Kişisel veri | **T.C. kimlik numarası, telefon, e-posta, adres gönderilmez.** Öğretmenler ad soyad (ve isteğe bağlı kurum sicil numarası) ile tanımlanır. |
| Boş değer | İsteğe bağlı alan yoksa ya hiç yazılmaz ya da `null` yazılır. |

---

## 2. Dosyanın yapısı

```json
{
  "bicim": "kamyosis-program",
  "surum": 1,
  "kaynak": { ... },
  "program": { ... },
  "ders_saatleri": [ ... ],
  "dersler": [ ... ],
  "ogretmenler": [ ... ],
  "derslikler": [ ... ],
  "kisimlar": [ ... ],
  "gruplar": [ ... ],
  "haftalik_dersler": [ ... ],
  "yerlesim": [ ... ]
}
```

### 2.1 Üst bilgiler

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `bicim` | metin | ✔ | Her zaman `"kamyosis-program"`. |
| `surum` | tam sayı | ✔ | Bu belgenin sürümü: `1`. |
| `kaynak.uygulama` | metin | ✔ | Üreten uygulamanın adı, ör. `"DersProgrami"`. |
| `kaynak.olusturma` | tarih-saat | ✔ | Dosyanın üretildiği an, ISO 8601, saat dilimiyle (`2026-11-03T14:05:00+03:00`). |
| `kaynak.aciklama` | metin | | Serbest not. |
| `program.id` | metin | ✔ | Programın kaynak uygulamadaki kimliği. |
| `program.ad` | metin | ✔ | Ör. `"2026-2027 Güz – 3 Kasım değişikliği"`. KAMYOSİS'te sürüm adı olur. |
| `program.donem` | metin | | Ör. `"2026-2027 Güz"`. |
| `program.onerilen_baslangic` | tarih | | Programın geçerli olması önerilen ilk gün (`2026-11-03`). Sadece öneridir; yayın tarihini KAMYOSİS'teki yetkili belirler. |

### 2.2 `ders_saatleri`

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `no` | tam sayı ≥ 1 | ✔ | Ders saati sırası. Benzersiz. |
| `baslangic` | `"SS:DD"` | ✔ | Ör. `"08:20"`. |
| `bitis` | `"SS:DD"` | ✔ | Ör. `"09:00"`. |

### 2.3 `dersler`

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `id` | metin | ✔ | Kalıcı kimlik. |
| `kod` | metin | ✔ | Ders kodu, ör. `"BİL103"`. Dosyada benzersiz. Kodun ilk rakamı sınıfı gösterir (1xx → 1. sınıf). |
| `ad` | metin | ✔ | Ders adının **tamamı** (kısaltılmamış). |

### 2.4 `ogretmenler`

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `id` | metin | ✔ | Kalıcı kimlik. |
| `ad_soyad` | metin | ✔ | Ör. `"Ayşe YILMAZ"`. KAMYOSİS personelle bu adla eşleştirir; büyük/küçük harf farkı önemli değildir. |
| `kisa_ad` | metin | | Programda görünen kısa ad. |
| `sicil` | metin | | Kurum sicil numarası (varsa). **T.C. kimlik no değil.** |

### 2.5 `derslikler`

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `id` | metin | ✔ | Kalıcı kimlik. |
| `ad` | metin | ✔ | Ör. `"BİL-Ağ Sistemleri Lab."`. Dosyada benzersiz. |
| `kapasite` | tam sayı | | Kişi sayısı. |

### 2.6 `kisimlar` (sınıf şubeleri)

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `id` | metin | ✔ | Kalıcı kimlik. |
| `kod` | metin | ✔ | Ör. `"1SVN"`, `"13İNŞ"`. Dosyada benzersiz. Rakamdan sonraki harfler bölüm kodudur. |
| `ad` | metin | ✔ | Ör. `"1.KISIM"`. |
| `tur` | metin | | `"normal"` (varsayılan), `"kredi"` (kredi tamamlama), `"hazirlik"` (Türkçe hazırlık). |
| `sinif` | tam sayı | | 1 veya 2. Yazılmazsa KAMYOSİS ders kodlarından bulur. |

### 2.7 `gruplar` (kısmın bölündüğü durumlar)

Bir kısmın tamamının girdiği dersler için grup **yazılmaz**. Sadece kısım bölünüyorsa (Grup 1 / Grup 2, Erkekler / Kızlar…) kullanılır.

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `id` | metin | ✔ | Kalıcı kimlik. |
| `kisim_id` | metin | ✔ | Ait olduğu kısım. |
| `ad` | metin | ✔ | Ör. `"Grup 1"`. Kısım içinde benzersiz. |
| `bolunme` | metin | | Birbirini tamamlayan gruplar aynı değeri taşır (Grup 1 ve Grup 2 → `"1"`; Erkekler ve Kızlar → `"2"`). |

### 2.8 `haftalik_dersler`

Bir dersin, bir (veya birkaç) kısma, belirli öğretmen(ler)le haftada kaç saat verildiğini tanımlar (aSc'deki *lesson*).

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `id` | metin | ✔ | Kalıcı kimlik. |
| `ders_id` | metin | ✔ | `dersler[].id` |
| `kisim_idleri` | metin listesi | ✔ | En az bir kısım. |
| `grup_idleri` | metin listesi | | Ders kısmın tamamına veriliyorsa boş liste. |
| `ogretmen_idleri` | metin listesi | ✔ | Bir veya daha fazla öğretmen. Boş olabilir ama KAMYOSİS'te ders takibine girmez. |
| `haftalik_saat` | sayı | ✔ | Haftalık toplam ders saati. **Bu dersin `yerlesim` kayıtlarının sayısına eşit olmalıdır.** |
| `blok` | tam sayı | | Ardışık saat sayısı (2 = iki saatlik blok). Varsayılan 1. |

### 2.9 `yerlesim` (programdaki hücreler)

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `haftalik_ders_id` | metin | ✔ | `haftalik_dersler[].id` |
| `gun` | 1–7 | ✔ | 1 = Pazartesi. |
| `saat` | tam sayı | ✔ | `ders_saatleri[].no` değerlerinden biri. |
| `derslik_id` | metin / null | | `derslikler[].id`. Derslik atanmamışsa `null`. |

---

## 3. Doğrulama listesi

KAMYOSİS dosyayı alırken şunları kontrol eder. **Kırmızı** olanlar dosyanın reddedilmesine, **sarı** olanlar uyarıya yol açar.

| | Kontrol |
|---|---|
| 🔴 | `bicim` = `"kamyosis-program"` ve `surum` = `1`. |
| 🔴 | Zorunlu alanlar dolu; türler doğru. |
| 🔴 | Her bağlantı (`ders_id`, `kisim_idleri`, `ogretmen_idleri`, `grup_idleri`, `haftalik_ders_id`, `derslik_id`, `kisim_id`) dosyada var olan bir kayda işaret ediyor. |
| 🔴 | Kimlikler kendi listesi içinde benzersiz; ders kodu, kısım kodu ve derslik adı benzersiz. |
| 🔴 | `gun` 1–7 arasında; `saat` tanımlı bir ders saati. |
| 🟡 | Her haftalık dersin `yerlesim` kayıt sayısı `haftalik_saat` ile aynı. |
| 🟡 | Aynı öğretmen aynı gün ve saatte iki farklı haftalık derste değil. |
| 🟡 | Aynı derslik aynı gün ve saatte iki farklı haftalık derste değil. |
| 🟡 | Aynı kısım aynı gün ve saatte iki derste değil (aynı bölünmenin farklı grupları hariç). |
| 🟡 | Ders kodunun öneki ve kısım kodundaki bölüm kodu KAMYOSİS'te tanımlı bir bölüme karşılık geliyor. |

---

## 4. Aktarım yolları

### 4.1 Dosya (birinci aşama)

Uygulama programı `.json` dosyası olarak indirtir. Kullanıcı dosyayı KAMYOSİS → Ders Planları → Program sürümleri ekranından yükler.

Önerilen dosya adı: `kamyosis_program_<program-id>_<YYYYAAGG-SSDD>.json`

### 4.2 Web adresi (ikinci aşama)

Uygulama aynı JSON'u kurum içi ağdan (Tailscale dahil) bir adreste sunar; KAMYOSİS bir düğmeyle çeker.

| İstek | Yanıt |
|---|---|
| `GET /api/kamyosis/programlar` | Mevcut programların listesi: `[{"id": "...", "ad": "...", "guncelleme": "2026-11-03T14:05:00+03:00"}]` |
| `GET /api/kamyosis/programlar/<id>` | Bu belgede tarif edilen tam JSON. |

- **Kimlik doğrulama:** `Authorization: Bearer <erişim-anahtarı>` başlığı. Anahtarı kaynak uygulama üretir, KAMYOSİS yöneticisine iletilir. Anahtar adreste (URL) gönderilmez.
- **Yanıt türü:** `Content-Type: application/json; charset=utf-8`
- **Hatalar:** 401 (anahtar yok/geçersiz), 404 (program yok). Gövde: `{"hata": "açıklama"}`.
- Yanıt **sadece okuma** amaçlıdır; KAMYOSİS kaynak uygulamada hiçbir şeyi değiştirmez.

---

## 5. aSc Timetables XML karşılıkları

Kaynak uygulama aSc XML'ini zaten biliyorsa, eşleme şöyledir:

| Bu biçim | aSc XML |
|---|---|
| `ders_saatleri` | `periods/period` (`period`, `starttime`, `endtime`) |
| `dersler` | `subjects/subject` (`short` → `kod`, `name` → `ad`) |
| `ogretmenler` | `teachers/teacher` (`name` → `ad_soyad`, `short` → `kisa_ad`) |
| `derslikler` | `classrooms/classroom` |
| `kisimlar` | `classes/class` (`short` → `kod`, `name` → `ad`) |
| `gruplar` | `groups/group` (`entireclass="1"` olanlar **yazılmaz**; `divisiontag` → `bolunme`) |
| `haftalik_dersler` | `lessons/lesson` (`periodsperweek` → `haftalik_saat`, `periodspercard`/`durationperiods` → `blok`) |
| `yerlesim` | `cards/card` — `days` bit dizisindeki her `1` için bir kayıt (`"10000"` → `gun: 1`); `period` → `saat`; `classroomids`'in ilki → `derslik_id` |

KAMYOSİS aSc XML'ini de doğrudan okuyabildiği için, kaynak uygulama aSc biçiminde (*aSc Timetables 2012 XML*) çıktı veriyorsa o da kabul edilir.

---

## 6. Sürüm geçmişi

| Sürüm | Tarih | Değişiklik |
|---|---|---|
| 1 | 2026-11-02 | İlk sürüm. |
