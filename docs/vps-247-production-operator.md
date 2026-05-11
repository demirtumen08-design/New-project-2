# Türkiye Gündemi 7/24 VPS Üretim Operatörü

Bu kurgu, Türkiye Gündemi'nin yerel bilgisayara bağlı kalmadan Linux VPS üzerinde haber taraması, haber aktarımı, statik site üretimi ve servis sağlığını 7/24 sürdürmesi için hazırlanmıştır.

## Üretim Bileşenleri

- `growth-os.service`: Admin paneli ve siteyi yerel `127.0.0.1:8080` üzerinde çalıştırır.
- `growth-os-newsbot.timer`: Haber robotunu her 5 dakikada bir çalıştırır.
- `growth-os-newsbot.service`: Kaynakları tarar, kalite kapısından geçen haberleri `published` olarak içeri alır ve siteyi yeniden üretir.
- `growth-os-operator.timer`: Üretim operatörünü her 5 dakikada bir çalıştırır.
- `growth-os-operator.service`: Dosya izinlerini düzeltir, servisleri ayakta tutar, sağlık uçlarını kontrol eder, site çıktısı bozuksa yeniden üretir ve haber robotu bayat kaldıysa tetikler.

## Haber Görselleri

Her haber yayınlanırken en az bir görsel alır. Varsayılan güvenli modda sistem, haber başlığı, kategori, kaynak ve anahtar kelimelerden özgün bir yerel PNG kapak görseli üretir. Görsel dosyaları şu dizine yazılır:

```text
/opt/growth-os/sites/turkiye-gundemi/public/assets/images/generated/
```

Eğer görsel üretimi için Pillow bulunamazsa sistem kategoriye göre yerel yedek görsel seçer:

- `son-dakika`: `/assets/images/son-dakika.png`
- `gundem`: `/assets/images/ankara.png`
- `ekonomi`: `/assets/images/ekonomi.png`
- `dunya`: `/assets/images/dunya.png`
- `teknoloji`: `/assets/images/teknoloji.png`
- `spor`: `/assets/images/spor.png`
- `kultur`: `/assets/images/kultur.png`

Kaynak sayfadan görsel indirme altyapısı da vardır; ancak telif kontrolü gerektirdiği için varsayılan olarak kapalı tutulur. Panelden “Kaynak görseli tara ve yerel olarak ekle” seçeneğiyle veya komut satırında `--enrich-images` / `--backfill-images` ile çalıştırılabilir.

Üretim operatörü her çalışmada eksik veya eski kategori görseline düşmüş haberler için haberle ilişkili yerel görsel üretir. Böylece kaynak görsel indirme kapalı olsa bile ana sayfa, kategori sayfaları, haber sayfası ve sosyal paylaşım metaları görselsiz kalmaz.

Arşiv için toplu üretim:

```bash
/opt/growth-os/venv/bin/python -m src.growth_os.news_automation --site turkiye-gundemi --backfill-images --publish-site
```

## VPS Kurulum Akışı

1. Ubuntu 24.04 veya Debian 12 tabanlı, public IPv4 adresli VPS açılır.
2. Sunucuya root olarak girilir.
3. İlk güvenlik ve sistem paketleri kurulur:

```bash
sudo ADMIN_USER=deploy SSH_PORT=22 bash ops/bootstrap_ubuntu_public.sh
```

4. Proje dosyaları VPS'e kopyalanır.
5. Model B ve 7/24 üretim servisleri kurulur:

```bash
sudo DOMAIN=turkiyegundemi.com bash ops/install_model_b.sh
```

Yerel projeden VPS'e tek seferde aktarım yapmak için:

```bash
VPS_HOST=VPS_PUBLIC_IPV4 VPS_USER=root DOMAIN=turkiyegundemi.com bash ops/deploy_to_vps.sh
```

İlk güvenlik hazırlığını da aynı aktarım betiğiyle yapmak gerekirse:

```bash
VPS_HOST=VPS_PUBLIC_IPV4 VPS_USER=root RUN_BOOTSTRAP=1 ADMIN_USER=deploy bash ops/deploy_to_vps.sh
```

Bu komut `bootstrap_ubuntu_public.sh` çalıştırdığı için SSH ayarlarını sertleştirir ve root girişini kapatır. Sonraki dağıtımlar için `deploy` kullanıcısıyla tekrar çalıştırılır:

```bash
VPS_HOST=VPS_PUBLIC_IPV4 VPS_USER=deploy DOMAIN=turkiyegundemi.com bash ops/deploy_to_vps.sh
```

6. Servisler kontrol edilir:

```bash
systemctl status growth-os
systemctl status growth-os-newsbot.timer
systemctl status growth-os-operator.timer
```

7. Canlı site kontrol edilir:

```bash
curl -I http://127.0.0.1/
curl http://127.0.0.1/healthz
```

## Domain Geçişi

Natro DNS üzerinde şu kayıtlar VPS public IPv4 adresine yönlendirilir:

```text
@    A    VPS_PUBLIC_IPV4
www  A    VPS_PUBLIC_IPV4
```

Ev/ofis statik IP yayını için mevcut IP:

```text
@    A    213.14.161.140
www  A    213.14.161.140
```

Windows + WSL üzerinde port geçişini yenilemek için Yönetici PowerShell'de:

```powershell
powershell -ExecutionPolicy Bypass -File ops/windows/configure-static-ip-hosting.ps1
```

DNS oturduktan sonra HTTPS kurulur:

```bash
sudo certbot --nginx -d turkiyegundemi.com -d www.turkiyegundemi.com
```

## Operatör Durum Dosyası

Üretim operatörü her çalışmada durum raporunu şuraya yazar:

```text
/opt/growth-os/content/turkiye-gundemi/production_operator_state.json
```

Bu dosyada servis durumu, sağlık kontrolü, haber robotu tetikleme bilgisi ve yayın sayıları görülebilir.

## Önemli Sınır

Yerel bilgisayar kapalıyken yayın üretiminin devam etmesi için sistemin VPS üzerinde çalışması şarttır. WSL veya yerel EXE yalnızca bilgisayar açıkken 7/24 döngüyü sürdürebilir.
