# Medyafaresi Growth OS

Bu klasor, Medyafaresi.com ve TurkiyeGundemi.com icin ortak calisabilecek, kendi sunucunuzda barindirilmaya uygun bir haber sitesi buyume ve teknik iyilestirme iskeletidir.

## Ne var?

- `src/growth_os/audit.py`: Medyafaresi ve rakip siteler icin teknik SEO, performans ve sitemap sinyallerini olcer.
- `src/growth_os/sitegen.py`: Turkiye Gundemi icin hizli, statik haber sitesi uretir.
- `src/growth_os/server.py`: Yerel kontrol paneli ve statik site sunucusu calistirir.
- `config/sites.json`: Site, rakip, kategori, SEO ve yayin politikalarinin manuel yonetildigi ana konfig.
- `config/context_graph.json`: Medyafaresi ve Turkiye Gundemi icin ortak "ag baglam" modeli.
- `docs/medyafaresi-audit.md`: Canli bulgular, rakip karsilastirmasi ve yol haritasi.

## Hızlı Baslangic

```powershell
python -m src.growth_os.sitegen --site turkiye-gundemi
python -m src.growth_os.audit --site medyafaresi --write reports
python -m src.growth_os.server --port 8080
```

Sonra tarayicida:

- Kontrol paneli: `http://localhost:8080/`
- Admin paneli: `http://localhost:8080/admin`
- Turkiye Gundemi sitesi: `http://localhost:8080/turkiye-gundemi/`

## Windows EXE Uretimi

```powershell
.\tools\package_windows.ps1
```

Uretim paketi:

```text
dist\TurkiyeGundemiApp\TurkiyeGundemiApp.exe
dist\TurkiyeGundemiApp\workspace\
```

`workspace` klasoru editlenebilir veridir. Haberler `workspace\content\turkiye-gundemi\articles.json`, site ayarlari `workspace\config\sites.json`, yayin ciktilari `workspace\sites\turkiye-gundemi\public` altinda durur.

## Model B Kurulumu

Public IP'li Linux sunucu hazirlama rehberi:

```text
docs/public-linux-server.md
```

Ev/ofis statik IP + modem port yonlendirme rehberi:

```text
docs/home-office-static-ip.md
```

Bu bilgisayarda sanal Linux sunucu kurma rehberi:

```text
docs/local-vm-setup.md
```

Yerel production benzeri test:

```powershell
.\tools\run_model_b_local.ps1
```

Linux sunucuda:

```bash
sudo DOMAIN=turkiyegundemi.com bash ops/install_model_b.sh
```

Model B'de public site `/` kokunde, admin paneli `/admin` yolunda, API `/api/` altinda calisir. Admin/API sifresi `GROWTH_OS_ADMIN_PASSWORD` ile verilir.

## Self-Hosted DNS

DNS'i de Model B sistemine almak icin:

```bash
python -m src.growth_os.dnsgen --site turkiye-gundemi --primary-ip 1.2.3.4 --secondary-ip 5.6.7.8
sudo PRIMARY_IP=1.2.3.4 SECONDARY_IP=5.6.7.8 bash ops/install_self_dns_bind9.sh
```

Natro tarafinda glue kayitlari ve nameserver degisimi gerekir:

```text
ns1.turkiyegundemi.com -> PRIMARY_IP
ns2.turkiyegundemi.com -> SECONDARY_IP
```

Detay: `docs/self-hosted-dns.md`.

## Tasarim Ilkesi

Bu sistem bir SaaS'a, Vercel/Netlify gibi yabanci platformlara veya kapali bir hosting saglayicisina bagimli degildir. Python standart kutuphanesiyle calisir; uretilecek statik dosyalar Nginx, Caddy, Apache veya dogrudan bu Python sunucusu ile yayinlanabilir.

## Manuel Genisletme

- Yeni site eklemek: `config/sites.json` icine yeni bir obje ekleyin.
- Yeni kural eklemek: `src/growth_os/audit.py` icindeki `build_recommendations` fonksiyonuna kural ekleyin.
- Yeni kategori eklemek: ilgili sitenin `categories` listesine slug ve ad ekleyin.
- Yeni haber eklemek: `content/turkiye-gundemi/articles.json` dosyasina haber objesi ekleyip `sitegen` calistirin.
