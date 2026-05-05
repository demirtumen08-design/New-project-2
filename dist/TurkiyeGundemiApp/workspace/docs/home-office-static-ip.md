# Statik IP + Modem Port Yonlendirme ile Model B

Bu modelde sunucu ev/ofis aginda calisir. ISS tarafindan verilen statik public IPv4 modem/router uzerindedir; modem gerekli portlari ic agdaki Linux sunucuya yonlendirir.

## Gereksinimler

- ISS'den alinmis statik public IPv4.
- CGNAT olmamali. Modemin WAN IP'si ile `curl -4 https://api.ipify.org` sonucu ayni olmali.
- 7/24 acik kalacak Linux makine veya mini PC. WSL2 HTTP testi icin uygundur; authoritative DNS icin bridged VM veya gercek Linux makine kullanin.
- Modemde port yonlendirme/NAT destegi.
- UPS onerilir.

## Ag Plani

Ornek:

```text
Public IP:      ISS tarafindan modem WAN'a verilen IP
Modem LAN:      192.168.1.1
Linux sunucu:   192.168.1.10
Domain:         turkiyegundemi.com
```

Linux sunucunun yerel IP'si sabitlenmelidir. Bunu iki yoldan biriyle yapin:

- Modem DHCP reservation: Linux makinenin MAC adresine `192.168.1.10` ayir.
- Linux uzerinde statik IP tanimla.

## Modem Port Yonlendirme

Modem panelinde NAT / Port Forwarding / Virtual Server bolumune su kurallar eklenir:

| Dis Port | Protokol | Ic IP | Ic Port | Amac |
| --- | --- | --- | --- | --- |
| 80 | TCP | 192.168.1.10 | 80 | HTTP ve Let's Encrypt dogrulama |
| 443 | TCP | 192.168.1.10 | 443 | HTTPS |
| 53 | UDP | 192.168.1.10 | 53 | Authoritative DNS |
| 53 | TCP | 192.168.1.10 | 53 | DNS buyuk cevap/zone islemleri |

SSH icin 22 portunu herkese acmak onerilmez. Daha guvenli secenekler:

- Sadece ofis IP'nize izin vermek.
- Farkli bir SSH portu kullanmak.
- VPN/WireGuard/Tailscale ile baglanmak.

SSH yine de acilacaksa:

| Dis Port | Protokol | Ic IP | Ic Port |
| --- | --- | --- | --- |
| 2222 | TCP | 192.168.1.10 | 22 |

## Linux Uzerinde Kurulum

Sunucuda:

```bash
sudo ADMIN_USER=deploy SSH_PORT=22 bash ops/bootstrap_ubuntu_public.sh
sudo DOMAIN=turkiyegundemi.com bash ops/install_model_b.sh
```

DNS'i de bu hatta almak icin:

```bash
sudo PRIMARY_IP=PUBLIC_STATIK_IP SECONDARY_IP=IKINCI_DNS_PUBLIC_IP bash ops/install_self_dns_bind9.sh
```

Tek IP ile test:

```bash
sudo PRIMARY_IP=PUBLIC_STATIK_IP SECONDARY_IP=PUBLIC_STATIK_IP bash ops/install_self_dns_bind9.sh
```

Tek IP uretimde onerilmez; `ns2` farkli bir hatta/sunucuda olmali.

## Natro Registrar Tarafi

Glue / child nameserver:

```text
ns1.turkiyegundemi.com -> PUBLIC_STATIK_IP
ns2.turkiyegundemi.com -> IKINCI_DNS_PUBLIC_IP
```

Domain nameserver:

```text
ns1.turkiyegundemi.com
ns2.turkiyegundemi.com
```

## Testler

Disaridan, mobil internet veya baska bir agdan:

```bash
curl -I http://PUBLIC_STATIK_IP
curl -I http://turkiyegundemi.com
dig @PUBLIC_STATIK_IP turkiyegundemi.com A
dig @PUBLIC_STATIK_IP www.turkiyegundemi.com A
```

Sunucudan:

```bash
curl -I http://127.0.0.1:8080/healthz
systemctl status growth-os
systemctl status nginx
systemctl status bind9
sudo ufw status
```

## SSL

DNS domaini public IP'ye cozdurduktan sonra:

```bash
sudo certbot --nginx -d turkiyegundemi.com -d www.turkiyegundemi.com
```

## Riskler ve Onlemler

- Ev/ofis interneti kesilirse site ve DNS gider.
- Elektrik kesintisi icin UPS gerekir.
- ISS 53/80/443 portlarini engelleyebilir; onceden test edilmeli.
- Modem firewall'u ve Linux UFW birlikte ayarlanmalidir.
- Admin/API public internete acik oldugu icin `GROWTH_OS_ADMIN_PASSWORD` guclu olmali ve Nginx'te IP/VPN kisiti eklenmelidir.
- DNS icin en az iki farkli public IP gerekir; tek IP sadece gecici testtir.
