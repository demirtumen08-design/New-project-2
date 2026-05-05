# Public IP'li Linux Sunucu Kurulumu

TurkiyeGundemi.com icin Model B'yi internete acmak istiyorsak en az bir public IPv4'li Linux sunucuya ihtiyacimiz var. DNS'i de kendi sistemimize almak istiyorsak ikinci nameserver icin ikinci public IPv4/sunucu gerekir.

## Onerilen Mimari

### Minimum test

- 1 sunucu
- Ubuntu Server 24.04 LTS
- 2 vCPU
- 4 GB RAM
- 40+ GB SSD
- 1 statik public IPv4
- Portlar: 22, 80, 443, 53 TCP/UDP

Bu test icin yeterlidir ama `ns1` ve `ns2` ayni makinede kalacagi icin DNS tarafinda uretim kalitesinde degildir.

### Uretim

- Ana sunucu: web + admin + Model B + BIND master
- Ikincil sunucu: sadece BIND secondary/slave
- Iki farkli public IPv4
- Mumkunse iki farkli fiziksel lokasyon veya en azindan iki farkli subnet

## Saglayici Secimi

Yurt disi PaaS'a baglanmak istemiyorsak su tip hizmetlerden biri secilmeli:

- Turkiye lokasyonlu VDS/VPS
- Turkiye lokasyonlu dedicated server
- Kendi fiziksel sunucunuz + veri merkezi colocation

Secerken sorulacaklar:

- Statik public IPv4 veriliyor mu?
- Reverse DNS ayarlanabiliyor mu?
- 53 UDP/TCP acik mi?
- Ek IPv4 veya ikinci kucuk sunucu alinabiliyor mu?
- Ubuntu Server 24.04 LTS kurulabiliyor mu?
- KVM/console erisimi var mi?
- Trafik limiti ve DDoS politikasi nedir?

## Ilk Kurulum

Sunucu Ubuntu 24.04 LTS ile acildiktan sonra root olarak girilir:

```bash
ssh root@SUNUCU_IP
```

Projeyi sunucuya kopyalamadan once temel guvenlik ve paketleri kur:

```bash
sudo ADMIN_USER=deploy bash ops/bootstrap_ubuntu_public.sh
```

Eger SSH sadece kendi IP'nizden acik olsun istiyorsaniz:

```bash
sudo ADMIN_USER=deploy ALLOW_SSH_FROM=OFIS_PUBLIC_IP bash ops/bootstrap_ubuntu_public.sh
```

Sonra yeni kullanici ile tekrar baglan:

```bash
ssh deploy@SUNUCU_IP
```

## Projeyi Sunucuya Kopyalama

Windows'tan PowerShell ile:

```powershell
scp -r "C:\Users\demir\OneDrive\Documents\New project 2" deploy@SUNUCU_IP:/tmp/growth-os
```

Sunucuda:

```bash
cd /tmp/growth-os
sudo DOMAIN=turkiyegundemi.com bash ops/install_model_b.sh
```

## DNS'i de Sunucuya Alma

Ana sunucu icin:

```bash
sudo PRIMARY_IP=ANA_SUNUCU_IP SECONDARY_IP=IKINCI_DNS_IP bash ops/install_self_dns_bind9.sh
```

Sonra Natro panelinde glue/child nameserver:

```text
ns1.turkiyegundemi.com -> ANA_SUNUCU_IP
ns2.turkiyegundemi.com -> IKINCI_DNS_IP
```

Domain nameserver:

```text
ns1.turkiyegundemi.com
ns2.turkiyegundemi.com
```

## Kontrol Komutlari

```bash
curl -I http://127.0.0.1:8080/healthz
systemctl status growth-os
systemctl status nginx
systemctl status bind9
dig @127.0.0.1 turkiyegundemi.com A
```

## SSL

DNS public sunucuya cozuldugunde:

```bash
sudo certbot --nginx -d turkiyegundemi.com -d www.turkiyegundemi.com
```

Certbot, Let's Encrypt sertifikasini alip Nginx'e uygular.
