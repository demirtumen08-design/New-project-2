# TurkiyeGundemi.com Self-Hosting Plani

Bu yapi yabanci PaaS servislerine bagli olmadan calisacak sekilde tasarlandi. Uretimde iki model var:

## Model A: Statik Site Yayini

En guvenli ve hizli model budur.

1. Admin uygulamasinda haberleri duzenleyin.
2. `Yayinla` butonu ile `workspace/sites/turkiye-gundemi/public` klasorunu uretin.
3. Bu klasoru sunucuya senkronize edin.
4. Nginx veya Caddy yalnizca statik dosya servis eder.

Avantaj: cok hizli, guvenli, az kaynak tuketir.

## Model B: Admin + Site Ayni Sunucuda

Growth OS uygulamasi sunucuda calisir, admin paneli sadece izinli IP/VPN arkasinda acilir.

### Hazirlanan kurulum

Bu repoda Model B icin hazir dosyalar:

- `ops/systemd/growth-os.service`
- `ops/systemd/growth-os.env.example`
- `ops/nginx/model-b-turkiyegundemi.conf`
- `ops/install_model_b.sh`
- `ops/install_self_dns_bind9.sh`
- `tools/run_model_b_local.ps1`

### Sunucuda kurulum

1. Linux sunucu kurulur.
2. Python 3.12+, rsync ve Nginx yuklenir.
3. Repo sunucuya kopyalanir.
4. Repo kokunden su komut calistirilir:

```bash
sudo DOMAIN=turkiyegundemi.com bash ops/install_model_b.sh
```

Kurulum su yolu kullanir:

- uygulama: `/opt/growth-os`
- ortam dosyasi: `/etc/growth-os/growth-os.env`
- servis: `growth-os`
- uygulama portu: `127.0.0.1:8080`

### Yerel Model B testi

Windows uzerinde:

```powershell
.\tools\run_model_b_local.ps1
```

Varsayilan lokal admin girisi:

```text
admin / admin12345
```

### Guvenlik

Model B'de public site `/` kokunden servis edilir. Admin ve API su yollar altinda kalir:

- `/admin`
- `/api/`

`GROWTH_OS_ADMIN_PASSWORD` set edilirse bu yollar HTTP Basic Auth ile korunur. Sunucuda parola `/etc/growth-os/growth-os.env` icinde tutulur. Nginx konfigurasyonunda `/admin` ve `/api/` icin ofis/VPN IP kisiti eklenebilir.

Servis durumu:

```bash
systemctl status growth-os
journalctl -u growth-os -f
```

Yayinlama admin panelindeki `Yayinla` butonu ile yapilir; statik HTML yine `sites/turkiye-gundemi/public` altina uretilir.

### DNS'i de kendi sunucumuza alma

Cloudflare/Natro DNS kullanmadan authoritative DNS'i Model B ekosistemine almak icin:

```bash
sudo PRIMARY_IP=1.2.3.4 SECONDARY_IP=5.6.7.8 bash ops/install_self_dns_bind9.sh
```

Detayli plan: `docs/self-hosted-dns.md`.

## Nginx Ornek Konfigurasyon

```nginx
# Model B icin asil dosya:
# ops/nginx/model-b-turkiyegundemi.conf
```

## Caddy Ornek Konfigurasyon

```caddyfile
turkiyegundemi.com, www.turkiyegundemi.com {
    root * /var/www/turkiyegundemi/public
    encode zstd gzip
    file_server
    header /assets/* Cache-Control "public, max-age=31536000, immutable"
    header Cache-Control "public, max-age=60, stale-while-revalidate=300"
}
```

## Yedekleme

Yedeklenmesi gereken ana klasorler:

- `workspace/config`
- `workspace/content`
- `workspace/sites/turkiye-gundemi/public`

Gunluk rsync veya restic yedegi onerilir.
