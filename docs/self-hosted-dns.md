# Self-Hosted DNS Plani

TurkiyeGundemi.com icin DNS'i Cloudflare veya Natro DNS yerine kendi Model B altyapimizdaki authoritative DNS'e alabiliriz. Bu islem iki parcadan olusur:

1. Model B sunucuda authoritative DNS servisi calisir.
2. Natro registrar panelinde domain nameserver'lari bizim `ns1/ns2` kayitlarimiza degistirilir.

## Kritik Notlar

- Tek DNS sunucusu uretim icin yeterli degildir. `ns1` Model B sunucuda, `ns2` farkli bir IP/sunucuda olmali.
- `ns1.turkiyegundemi.com` ve `ns2.turkiyegundemi.com` domainin kendi alt alanlari oldugu icin registrar panelinde glue/host records gerekir.
- DNS servisi icin UDP 53 ve TCP 53 dis dunyaya acik olmali.
- DNS sunucusu recursive olmamali; sadece authoritative cevap vermeli. Bu repo BIND9 konfigurasyonunu `recursion no` ile uretir.
- WSL2, Windows'un 53. port/DNS tunneling katmani nedeniyle authoritative DNS icin uretim hedefi olarak onerilmez. DNS'i kendiniz barindiracaksaniz bridged network'lu VirtualBox/Proxmox/gercek Linux makine veya public Linux sunucu kullanin.

## Uretilen Dosyalar

- `src/growth_os/dnsgen.py`: BIND zone dosyasi uretir.
- `ops/install_self_dns_bind9.sh`: Linux sunucuda BIND9 kurar.
- `ops/dns/named.conf.options.authoritative`: recursive olmayan BIND ayari.
- Admin panelindeki `DNS` sekmesi: zone dosyalarini sistemden uretir.

## Zone Dosyasi Uretme

Yerel veya sunucuda:

```bash
python -m src.growth_os.dnsgen --site turkiye-gundemi --primary-ip 1.2.3.4 --secondary-ip 5.6.7.8
```

Cikti:

```text
ops/dns/generated/db.turkiyegundemi.com
ops/dns/generated/named.conf.local
ops/dns/generated/named.conf.options.authoritative
```

## Sunucuda BIND9 Kurulumu

Model B kurulduktan sonra:

```bash
sudo PRIMARY_IP=1.2.3.4 SECONDARY_IP=5.6.7.8 bash ops/install_self_dns_bind9.sh
```

Kontrol:

```bash
systemctl status bind9
named-checkconf
named-checkzone turkiyegundemi.com /etc/bind/zones/db.turkiyegundemi.com
dig @127.0.0.1 turkiyegundemi.com A
dig @127.0.0.1 www.turkiyegundemi.com A
```

## Natro Registrar Tarafi

Natro panelinde iki islem gerekir:

1. Child nameserver / host record / glue kaydi olustur:

```text
ns1.turkiyegundemi.com -> PRIMARY_IP
ns2.turkiyegundemi.com -> SECONDARY_IP
```

2. Domain nameserver'larini degistir:

```text
ns1.turkiyegundemi.com
ns2.turkiyegundemi.com
```

Degisimden sonra yayilim 5 dakika ile 48 saat arasi surebilir.

## Baslangic Zone Kayitlari

Bu sistem sunlari uretir:

- `A @ -> PRIMARY_IP`
- `A www -> PRIMARY_IP`
- `A ns1 -> PRIMARY_IP`
- `A ns2 -> SECONDARY_IP`
- `TXT @ -> v=spf1 -all`
- `TXT _dmarc -> reject policy`
- `CAA @ -> letsencrypt.org`

E-posta kullanmaya baslamadan once MX/SPF/DKIM/DMARC kayitlari ayrica tasarlanmalidir.
