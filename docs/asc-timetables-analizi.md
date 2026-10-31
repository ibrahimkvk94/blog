# aSc TimeTables — Çalışma Prensibi ve Benzer Bir Sistemin Tasarımı

> Bu doküman iki kaynaktan beslenir:
> **(R)** aSc'nin kendi yardım sayfalarında ve XML dışa aktarımında doğrulanmış bilgiler,
> **(Ç)** aSc'nin iç algoritmasını yayımlamadığı noktalarda, davranışından ve okul ders programı
> (school timetabling) literatüründen yapılan **çıkarımlar**. Çıkarımlar ayrıca işaretlenmiştir.

---

## 1. Ürün özeti

| Bileşen | Görev |
|---|---|
| **aSc TimeTables (masaüstü, Windows)** | Veri girişi, kısıtlar, otomatik üretici (generator), elle düzenleme, raporlar, dışa aktarım |
| **aSc TimeTables Online** | Aynı modelin tarayıcı sürümü; bulutta üretim (veri merkezindeki sunucuda generator çalışır, ilerleme başka cihazdan izlenir) |
| **EduPage** | Yayımlama (öğrenci/öğretmen/veli görünümü), **nöbet/vekâlet (substitution)** modülü, e‑okul işlevleri |

Ana fikir: program **ders (lesson)** tanımlarından **kartlar (card)** üretir ve bu kartları
`gün × saat × (hafta) × (dönem)` ızgarasına, tüm kaynak çakışmalarını ve kısıtları gözeterek yerleştirir. (R)

---

## 2. Veri modeli (çekirdek)

aSc'nin XML dışa aktarımındaki tablo adları iç modeli neredeyse birebir yansıtır (R):

```
<timetable>
  <periods>      <period period="1" name short starttime endtime/>          ders saatleri
  <daysdefs>     <daysdef id name short days="10000,01000,..."/>             gün tanımları (bitmask)
  <weeksdefs>    <weeksdef id name short weeks="10,01,11"/>                  hafta tanımları (A/B hafta)
  <termsdefs>    <termsdef id name short terms="10,01,11"/>                  dönem tanımları
  <subjects>     <subject id name short/>
  <teachers>     <teacher id firstname lastname short gender color/>
  <buildings>    <building id name/>
  <classrooms>   <classroom id name short capacity buildingid/>
  <grades>       <grade grade name short/>
  <classes>      <class id name short teacherid classroomids grade/>
  <groups>       <group id name classid entireclass divisiontag studentcount/>
  <students> / <studentsubjects>                                             (öğrenci bazlı program için)
  <lessons>      <lesson id classids groupids subjectid teacherids classroomids
                         periodspercard periodsperweek daysdefid weeksdefid termsdefid
                         seminargroup capacity partner_id/>
  <cards>        <card lessonid classroomids period days weeks terms/>
</timetable>
```

### 2.1 Zaman boyutu
- **Periods (ders saatleri):** numara + başlangıç/bitiş saati. Teneffüs/öğle arası saat değil; aralarda kalan boşluktur.
- **Days:** haftadaki gün sayısı ayarlanır. `daysdef` bir **bitmask kümesidir**: `"10000,01000,00100"` = "Pzt veya Sal veya Çar'dan herhangi biri". Bir derse daysdef bağlanınca kartı yalnızca o günlerden birine konabilir. (R)
- **Weeks:** çok haftalı (A/B, tek/çift hafta) programlar. Kartta `weeks="10"` → sadece 1. hafta; `"11"` → her hafta. (R)
- **Terms:** dönem (yarıyıl/çeyrek). Aynı mantık; bir ders yalnızca güz döneminde olabilir. (R)

> Tasarım dersi: **zaman = (gün, saat) çifti; hafta ve dönem ise bitmask ile "paralel evrenler"**. İki kart ancak
> gün‑saat aynı **ve** `weeks & weeks' != 0` **ve** `terms & terms' != 0` ise çakışır.

### 2.2 Sınıf, bölünme (division) ve grup — çakışma semantiğinin kalbi
- Her sınıfın bir veya daha çok **division**'ı vardır. Bir division, sınıfı tamamen kapsayan grupların kümesidir (ör. *Kızlar/Erkekler*, *1.Grup/2.Grup*, *Almanca/Fransızca*). Her öğrenci her division'da **tam bir** gruba aittir. (R)
- Bir ders ya **tüm sınıfa** ya da **bir gruba** atanır. (R)
- **Çakışma kuralı (R):**
  - Aynı division'daki farklı gruplar **aynı anda** ders görebilir (öğrenci kümeleri ayrık).
  - Farklı division'lardaki gruplar **çakışır** (öğrenci kümeleri kesişir — "Kızlar" ile "1.Grup").
  - "Tüm sınıf" her grupla çakışır.
- İki division'ı aynı saate oturtmak gerekiyorsa, aSc'nin önerisi gruplarının **kesişimlerinden** oluşan birleşik division yaratmaktır. (R)
- **Birleşik dersler (joint classes):** bir ders birden çok sınıfı/grubu içerebilir (`classids="A,B" groupids="gA,gB"` — sıralı eşleşir). (R)

> Uygulamada: her grubu **atomik öğrenci kümelerinin** (division’ların kartezyen çarpımı hücreleri) bir birleşimi olarak
> modelleyin. İki ders çakışır ⇔ atom kümeleri kesişir. Bu, division mantığını genel ve hatasız hale getirir.

### 2.3 Ders (lesson) ve kart (card)
- **Lesson** = "Ne, kime, kim tarafından, haftada kaç saat": konu + sınıf(lar)/grup(lar) + öğretmen(ler) + izinli derslikler + `periodsperweek` + `periodspercard` (kart uzunluğu: 1=tekil, 2=blok/çift ders). (R)
- Bir lesson'dan `periodsperweek / periodspercard` adet **kart** doğar. Haftada 5 saat, uzunluk 1 → 5 kart; haftada 4 saat çift ders → 2 kart. Karışık dağılım (ör. "2+2+1") da tanımlanabilir. (R)
- **Card** = yerleştirilmiş tek bir oturum: `(lesson, gün, başlangıç saati, derslik, hafta, dönem)`. (R)
- **Derslik:** lesson birden çok aday derslik listeleyebilir; generator kartı **bunlardan birine** atar. Sınıfın "ev dersliği" (home classroom) ve paylaşılan derslikler (laboratuvar, spor salonu) ayrımı vardır. (R)
- **Kilitli kart (locked):** üretimde yerinden oynamaz; aSc "yalnızca gerçekten kilitlenmesi gerekeni kilitleyin" der — kilitler arama uzayını daraltıp çözümü imkânsızlaştırabilir. (R)
- **Seminer/kurs dersleri:** öğrencilerin bireysel seçimlerinden oluşan gruplar (seçmeli dersler). Grup alanında "Seminar" seçilir; generator, öğrenci çakışmalarını kontrol eder ve gerekirse öğrenciyi aynı kursun başka şubesine (section) kaydırır; şube kapasitesi tanımlıdır. (R)

---

## 3. Kısıtlar (constraints)

### 3.1 Zaman müsaitliği (time‑off) — üç durumlu
Öğretmen, sınıf, ders(konu), derslik ve tekil ders için gün×saat ızgarası (R):
- ✔ uygun, ✘ yasak, **?** koşullu ("bu işaretli hücrelerden en fazla N tanesi kullanılsın" — ör. 6. saate haftada en fazla 2 kez).

### 3.2 Öğretmen kısıtları (R)
- Haftalık ve günlük **en fazla boşluk (pencere/gap)** — genel ayar *Timetable → Parameters*, öğretmen bazında özelleştirme.
- Günde **en fazla ders saati**, istisnalı ("günde max 4, ama haftada iki gün 5 olabilir").
- **En fazla ardışık ders**; 2027 ile "uzatılmış" sürüm: yalnızca günlük yük eşiği aşıldığında uygulanır (#84).
- Çalıştığı **gün sayısı** (min/max), boş gün istekleri.
- **Bina değişimi**: günde en fazla bina değişimi; haftada en fazla bina sayısı.
- **Öğle arası**: "3–5. saatler arasında en fazla 2 ders" biçiminde ifade edilir.

### 3.3 Sınıf kısıtları (R/Ç)
- Sınıf programında boşluk genelde **yasak** (öğrenciler boşta kalmaz); grup bölünmelerinde "grup boşluğu" kontrolü ayrıca yapılır.
- Gün içinde min/max ders, ilk saatten başlama, öğle arası.

### 3.4 Konu/ders dağılım kısıtları (R)
- **Dağılım kaydırıcısı (Subjects → Constraints):** sağa çektikçe ders hafta içine daha **eşit** yayılır; sola çektikçe "aynı gün en fazla 1" / "dersler arası min gün" gibi kurallar gevşer.
- Ağır derslerin (matematik vb.) tercih edilen saatleri, aynı günde ikinci kez gelmemesi, çift dersin teneffüsü aşmaması.

### 3.5 Kart ilişkileri (card relationships) — genel kısıt dili (R)
Seçili nesne kümesine (öğretmenler/sınıflar/konular/dersler) **toplu** kural uygular. Tipik koşullar:
- Aynı gün / farklı günler / ardışık / aynı anda (eşzamanlı) / belirli sıra (A, B'den önce).
- Günde/haftada en fazla N; **"Apply to"** alanı kuralın kapsamını değiştirir (ör. "her öğretmen için ayrı ayrı: 6–10. saatlerde dersi olan en fazla 1 gün").
- Yeni tipler: haftada en fazla bina sayısı, iki ders arasında en az N boş gün (hafta sonu sayılmadan).
- Tek bir ilişkiyi test etme: *Test → Card relationships* — yalnızca o ilişkinin kartlarını üretip kuralın doğru yazılıp yazılmadığını gösterir.

### 3.6 Kısıt sertliği
- Varsayılan: kısıtların hepsi **sert** gibi davranır; **Constraints relaxation** açıksa generator, bir kartla "büyük belaya" girdiğinde kartı kısıt ihlal ederek de olsa yerleştirir ve sonuçta isteklere **en yakın** programı hedefler. **Strict** modda hiçbir kısıt gevşetilmez; uygun program yoksa kartlar boşta kalabilir. (R)
- 2024+: **"Relaxed based on importance"** — kartları programa yerleştirmeye kısıtları sağlamaktan çok daha yüksek öncelik verir, kartları programdan çıkarmaz; kısıtların bir önem derecesi vardır. (R)
- 2026: belirli kısıt **kümelerinin** gevşetildiği "taslak üretim"; üretilemeyen **küçük alt kümeleri** (çözülemez çekirdek) bulma. (R)

---

## 4. Üretim (generation) iş akışı

1. **Veri denetimi (data check / Test):** üretim başlarken veri kontrol edilir. Tipik kontroller (R/Ç):
   - öğretmenin toplam ders saati > müsait hücre sayısı,
   - sınıfın haftalık yükü > (gün × saat),
   - çift ders için uygun ardışık hücre yok,
   - dersliğe ihtiyaç duyan kart sayısı > dersliğin müsait hücresi,
   - daysdef/time‑off kesişimi boş,
   - "aynı anda" ilişkisinde grupların çakışması.
2. **Generator:** "bekleyen (pending) kart kalmayan ve hiçbir kısıtı gevşetilmemiş program bulunana kadar" çalışır; kullanıcı istediği an durdurup en iyi sonucu alabilir. (R)
   - Kısmi üretim: yalnızca seçilen sınıflar/kartlar; kilitli kartlar sabit.
   - Karmaşıklık seviyesi: "Normal" ilk denemeler için; karmaşık programlarda daha yüksek seviye. (R)
   - Bulut üretim; 2027'de "kendini değiştiren (self‑modifying) generator" — veriye göre stratejisini ayarlıyor. (R, detay yayımlanmamış)
3. **Analyze by generation:** 1 dakika üretip en çok sorun çıkaran kartları **kırmızı** (zor) olarak boyar; çoğu zaman veri hatasını açığa çıkarır. (R)
4. **Doğrulama (Verification):** bitmiş programda kırılan/gevşetilen kısıtların listesi. (R)
5. **Elle düzenleme:** kartı sürükleyince her hücre için uygunluk renklendirilir; çakışan kart gösterilir; kart "bekleyenler" alanına geri atılabilir. (R)
6. **Yayımlama ve vekâlet:** EduPage'e aktarım, nöbet/vekâlet yönetimi; XML/CSV dışa aktarım (varsayılan XML iç ID'leri kullanır; konfigürasyon dosyasıyla kendi ID'leriniz ve ek sütunlar). (R)

### 4.1 Generator iç mantığı — çıkarım (Ç)
aSc algoritmasını açıklamıyor; ancak gözlenen davranış şunlarla birebir uyuşuyor:
- **"Pending card" kuyruğu + "en zor kart önce"** sıralaması (az uygun hücresi olan, uzun, çok kaynaklı kartlar önce).
- Kart yerleştirilemediğinde **ejection chain / çatışmalı yerleştirme**: kart en az zararlı hücreye zorla konur, çakışan kartlar programdan sökülüp kuyruğa geri atılır. "Analyze"ın kırmızı kartları, bu söküp‑takma döngüsünde en sık hareket eden kartlardır.
- **Tabu / yaşlandırma (aging):** yeni sökülen kartın hemen eski yerine dönmesini engelleyen bellek; aksi halde döngüye girer.
- **Rastgele yeniden başlatma**: farklı tohumlarla yeniden deneme ("bir sonraki üretim farklı sonuç verir" davranışı).
- Gevşetme modunda yumuşak kısıt ihlali bir **ceza puanı**na dönüşür; strict modda yasak hücredir.

Bu, literatürde çok iyi bilinen **yapıcı sezgisel + yerel arama (ejection chains, tabu search, simulated annealing)** ailesidir ve ITC 2011 / XHSTT yarışmalarındaki başarılı çözücülerle aynı yaklaşımdır.

---

## 5. Benzer bir sistemin tasarımı

### 5.1 Mimari
```
┌────────────┐   REST/WS    ┌──────────────────┐   iş kuyruğu   ┌────────────────────┐
│ Web arayüz │ ───────────▶ │ API (Django/DRF) │ ─────────────▶ │ Solver worker(lar)ı│
│ grid + DnD │ ◀─ canlı ─── │  PostgreSQL      │ ◀─ ilerleme ── │ Celery / RQ        │
└────────────┘   ilerleme   └──────────────────┘                │ OR-Tools + sezgisel│
                                                                └────────────────────┘
        yayın: öğrenci/öğretmen görünümü, iCal, PDF, aSc‑uyumlu XML, vekâlet modülü
```
- Solver'ı **ayrı süreçte** çalıştırın; model JSON'a serileştirilip işçiye verilir, ara sonuçlar (yerleşen kart sayısı, ceza) WebSocket ile akar.
- Her üretim bir **sürüm (snapshot)** olarak saklanır; kullanıcı karşılaştırıp seçer.

### 5.2 Veritabanı şeması (özet)
```
School(id, days_count, periods_count, weeks_count, terms_count)
Period(school, index, start, end)
DaysDef/WeeksDef/TermsDef(id, name, masks: int[])      -- izinli bitmask seçenekleri
Building, Classroom(capacity, building)
Subject, Teacher, Class(home_classroom)
Division(class), Group(division, name, student_count)   -- Division→Group; "entire class" sanal grup
Student, StudentGroup, StudentCourse                    -- seminer/seçmeli
Lesson(subject, periods_per_week, card_length_pattern int[], daysdef, weeksdef, termsdef)
LessonGroup(lesson, group)  LessonTeacher(lesson, teacher)  LessonRoomOption(lesson, room | room_set)
Card(lesson, day, period, room, weeks_mask, terms_mask, locked bool)
Availability(entity_type, entity_id, day, period, state ∈ {OK, NO, MAYBE})
Constraint(type, scope_json, params_json, weight, hard bool)   -- genel kısıt tablosu
Relationship(condition, apply_to, targets_json, params_json, weight)
Substitution(date, card, absent_teacher, substitute_teacher, room)
```

### 5.3 Ön işleme (çözüm kalitesini en çok etkileyen kısım)
1. **Atomik öğrenci kümeleri:** her sınıf için division'ların kartezyen çarpımı → atomlar. Her grup = atom kümesi. Kart kaynakları: `{teachers} ∪ {atoms} ∪ {room}`.
2. **Alan (domain) hesaplama:** her kart için olası `(gün, başlangıç)` çiftleri = tüm kaynakların müsaitliği ∩ daysdef ∩ "kart uzunluğu teneffüs/gün sonunu aşmasın".
3. **Fizibilite denetimleri (aSc "Test" eşdeğeri):** yük ≤ müsait hücre (öğretmen, atom, derslik türü), Hall evlilik koşulu ile derslik kapasite kontrolü, boş alanlı kart. Hata mesajları kullanıcıya **hangi verinin** sorunlu olduğunu söylemeli.

### 5.4 Çözücü seçenekleri

**A) CP‑SAT (Google OR‑Tools) — önerilen başlangıç**
```
x[c,d,p] ∈ {0,1}          kart c, gün d, saat p'de başlar (yalnızca alan içindekiler yaratılır)
Σ_{d,p} x[c,d,p] = 1                                   her kart bir kez
∀ kaynak r, d, t:  Σ_{c∋r, p≤t<p+len(c)} x[c,d,p] ≤ 1      çakışma (hafta/dönem maskesi kesişenler için)
y[c,room] ;  Σ_room y = 1 ;  oda doluluğu için z[c,room,d,p] = x ∧ y   (veya oda atamasını 2. aşamaya bırak)
Aynı lesson'ın kartları: gün başına ≤ 1  (dağılım), simetri kırma: kart_i.gün < kart_{i+1}.gün
Öğretmen boşluğu: busy[t,d,p] bool; gap = busy önce ∧ ¬busy ∧ busy sonra (first/last yardımcı değişkenleri ile)
Amaç: min Σ w_k · ihlal_k   (yumuşak kısıtlar)
```
- Avantaj: hızlı prototip, çözülemezlikte **varsayım çekirdeği (assumptions/unsat core)** ile aSc 2026'daki "çözülemeyen alt küme" özelliğinin doğrudan karşılığı.
- Büyük okullarda (≈1500+ kart) tek parça model ağırlaşır → **ayrıştırma**: önce zaman (oda kapasitesini toplu kısıt olarak), sonra oda ataması (bipartite eşleme / küçük MIP), sonra yerel iyileştirme.

**B) Özel sezgisel (aSc tarzı) — ölçek ve etkileşim için**
```
pending ← tüm kilitsiz kartlar, zorluk puanına göre sırala
while pending ≠ ∅ and süre kalmışsa:
    c ← en zor kart (az alan, uzun, çok kaynak, yüksek "taşınma sayısı")
    for slot in alan(c):  maliyet(slot) = sert_çakışan_kart_sayısı·W_hard + yumuşak_ceza + tabu_cezası
    slot* ← en düşük maliyet (eşitlikte rastgele)
    çakışan kartları sök → pending'e geri at, taşınma sayılarını artır, tabu'ya yaz
    c'yi slot*'a yerleştir
yerel iyileştirme: swap / kick / Kempe zinciri hamleleri + simulated annealing (yumuşak cezaları düşür)
```
- "Analyze" özelliği = taşınma sayısı en yüksek kartların raporu.
- "Relaxation" = sert kısıtları ağır cezalı yumuşağa çevirmek; "importance" = ağırlık katmanları.
- Hibrit en iyisi: CP‑SAT ile başlangıç çözümü + sezgisel ile çok hızlı **etkileşimli onarım** (kullanıcı bir kartı taşıdığında anında yeniden yerleşim).

### 5.5 Kısıt motoru tasarımı
- Her kısıt bir sınıf: `domain_filter()` (sert, ön işleme), `delta_cost(move)` (artımlı ceza), `cp_sat_encode(model)` ve `explain(violation)`.
- **Artımlı değerlendirme** şart: her hamlede yalnızca etkilenen öğretmen/atom/gün yeniden hesaplanır.
- Kart ilişkileri için küçük bir DSL: `{"condition": "different_days", "apply_to": "each_teacher", "targets": {...}, "weight": 100}`.

### 5.6 Kullanıcı deneyimi (aSc'nin güçlü olduğu yer)
- Sürükle‑bırak ızgara; kart tutulduğunda her hücre yeşil/sarı/kırmızı ve çakışan kart ipucu.
- Bekleyen kartlar alanı, kilitleme, kısmi üretim (seçili sınıflar), üretim sırasında canlı en iyi sonuç.
- Doğrulama raporu: kısıt → ihlal eden kartlar → tıkla ve git.
- Ana programdan **günlük vekâlet**: devamsız öğretmenin kartlarına müsait + aynı branş + az yüklü öğretmen öner.

### 5.7 Türkiye'ye özel notlar (Ç)
- MEB yapısı: haftalık ders çizelgesi, sınıf öğretmenliği, ortak dersler (Din/Seçmeli), **nöbet** çizelgesi; e‑Okul'a aktarım için CSV/Excel çıktısı.
- Birleştirilmiş sınıflar ve seçmeli derslerin tamamı division/seminer modeliyle karşılanır.
- Öğretmen "boş gün" talebi ve ikili öğretim (sabahçı/öğlenci) → sınıf müsaitliği + vardiya bazlı period tanımı.

### 5.8 Yol haritası
1. Veri modeli + içe/dışa aktarım (aSc XML okuyucu ile gerçek veriyle test).
2. Ön işleme + fizibilite raporu.
3. CP‑SAT ile sert kısıtlar → ilk geçerli program.
4. Yumuşak kısıtlar, ağırlıklar, gevşetme modları, unsat core açıklaması.
5. Etkileşimli ızgara + artımlı sezgisel onarım.
6. Yayın, vekâlet modülü, çok hafta/dönem, seminer (öğrenci bazlı) programlar.

---

## Kaynaklar
- Constraints relaxation — https://help.asctimetables.com/text.php?id=113&lang=en
- Analyze the timetable by generation — https://help.asctimetables.com/text.php?id=1183&lang=en
- Divisions — https://help.asctimetables.com/text.php?id=465 ; iki division'ı birleştirme — https://help.asctimetables.com/text.php?id=239&lang=en
- Groups and divisions — https://help.edupage.org/?id=1037&lang_id=1
- Windows (gaps) in teachers timetables — https://help.edupage.org/?lang_id=1&p=u1%2Fu3%2Fu57%2Fu79%2Ft168
- Öğle arası — https://help.asctimetables.com/text.php?id=719&lang=en
- Testing card relationships — https://help.edupage.org/?lang_id=1&p=u1%2Fu3%2Fu59%2Ft1136
- Seminer dersleri — https://help.edupage.org/?lang_id=1&p=u1%2Fu3%2Fu63%2Ft291 , https://help.edupage.org/?lang_id=1&p=u1%2Fu3%2Fu63%2Ft293
- What's new 2024 / 2025 / 2027 — https://help.edupage.org/?lang_id=1&p=u1%2Fu3%2Fu104%2Fu4743 , https://help.edupage.org/?p=u1%2Fu3%2Fu104%2Fu6303&lang_id=1 , https://help.edupage.org/?p=u1%2Fu3%2Fu104%2Fu8985&lang_id=1
- Export to XML — https://help.edupage.org/?lang_id=1&p=u1%2Fu3%2Fu64%2Ft699
- XML yapısı (ikincil) — https://gist.github.com/brainysmurf/8a5289de680a5272956e819ff1ebf794 , https://github.com/transformteamsg/reliefcher/issues/798
