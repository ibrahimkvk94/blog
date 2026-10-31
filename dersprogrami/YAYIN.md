# Sunucuya kurulum (tüm okullar tek adreste)

Bu rehber programı bir sunucuya kurup tüm kurumların aynı adresten (ör. `https://program.okulum.edu.tr`)
kullanmasını sağlar. Kurulum Docker ile yapılır; HTTPS sertifikası, veritabanı, üretim kuyruğu ve
günlük yedek kendiliğinden çalışır. Yaklaşık 15 dakika sürer.

## Neler kurulur?

| Parça | Görevi |
|---|---|
| **PostgreSQL** | Veritabanı: çok kullanıcı aynı anda çalışırken kilitlenmez |
| **web** | Uygulama (birden çok süreçle) |
| **worker** | Üretim kuyruğu: “Üretimi başlat” denince iş sıraya girer ve burada çalışır; web yeniden başlasa da sürer |
| **backup** | Her gün otomatik yedek (son 30 gün saklanır) |
| **Caddy** | HTTPS: Let's Encrypt sertifikasını kendisi alır ve yeniler |

## 1. Sunucu ve alan adı

1. Bir Linux sunucu (Ubuntu 22.04/24.04; en az 4 çekirdek, 8 GB bellek önerilir) kiralayın ya da okulun sunucusunu kullanın.
2. Alan adınızın DNS ayarına bir **A kaydı** ekleyin: `program.okulum.edu.tr → sunucunun IP adresi`.
3. Sunucuda 80 ve 443 numaralı portlar açık olmalı.

## 2. Docker'ı kurun (bir kez)

Sunucuya SSH ile bağlanıp şunu yazın:
```
curl -fsSL https://get.docker.com | sh
```

## 3. Programı indirin ve ayarlayın

```
git clone -b claude/elegant-fermi-mtxjbt https://github.com/ibrahimkvk94/blog.git
cd blog/dersprogrami
cp .env.example .env
nano .env
```
`.env` içinde alan adını, rastgele uzun bir `DJANGO_SECRET_KEY`, veritabanı parolasını ve merkez
yönetici kullanıcı adı/parolasını yazın. Kaydedip çıkın (Ctrl+O, Enter, Ctrl+X).

## 4. Başlatın

```
docker compose up -d --build
```
Birkaç dakika sonra `https://alan-adınız` açılır. `.env`'deki merkez yönetici hesabıyla girin.
**Merkez paneli**nden kurumları ekleyip kurum yöneticilerini atayın; yöneticiler kendi kullanıcılarını açar.

## Güncelleme

```
cd blog/dersprogrami
git pull
docker compose up -d --build
```
Veritabanı değişiklikleri açılışta kendiliğinden uygulanır.

## Yedekler

- Her gün otomatik yedek alınır. **Merkez paneli → Yedekler** sayfasından “Şimdi yedek al” ile anında yedek alabilir ve yedekleri indirebilirsiniz.
- Yedekleri ara sıra indirip başka bir yerde de saklayın.
- Geri yükleme (boş bir kurulumda):
  ```
  docker compose cp yedek-....json.gz web:/tmp/yedek.json.gz
  docker compose exec web python manage.py loaddata /tmp/yedek.json.gz
  ```

## Yerel bilgisayardan sunucuya taşıma

Yerel kurulumda (calistir.bat) **Merkez paneli → Yedekler → Şimdi yedek al → İndir** deyin, dosyayı
sunucuya kopyalayıp yukarıdaki geri yükleme komutlarını çalıştırın.

## Sorun giderme

| Sorun | Çözüm |
|---|---|
| Site açılmıyor / sertifika hatası | DNS kaydının sunucuyu gösterdiğini ve 80/443 portlarının açık olduğunu kontrol edin: `docker compose logs caddy` |
| Üretim “sırada” kalıyor | Çalışan süreci kontrol edin: `docker compose logs worker` |
| Genel kayıtlar | `docker compose logs -f web` |
