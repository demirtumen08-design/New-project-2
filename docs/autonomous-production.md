# 7/24 Otonom Haber Üretimi ve IP Değişikliği Onarımı

Bu sürümde haber robotu yalnızca RSS tarayan bir komut olmaktan çıkarılıp otonom üretim döngüsüne bağlandı.

## Ne yapar?

- Linux sunucusu veya VirtualBox içinde değişen IP adresini algılar.
- Yerel IP ve public IP bilgisini ayrı ayrı toplar.
- `config/sites.json` içindeki DNS `A` kayıtlarını otomatik günceller.
- BIND zone dosyalarını yeniden üretir.
- Statik site üretimini kesintisiz devam ettirir.
- Her döngüde haber import, görsel zenginleştirme ve yayınlama adımlarını çalıştırır.
- Ağ/kaynak hatası olduğunda servis düşmez; hata state dosyasına yazılır ve sonraki döngüde devam eder.
- Çalışma sentezini `sites/turkiye-gundemi/public/runtime-synthesis.json` içine yazar.

## Linux systemd kurulumu

```bash
sudo cp ops/systemd/growth-os-autonomous.service /etc/systemd/system/
sudo cp ops/systemd/growth-os-network-heal.service /etc/systemd/system/
sudo cp ops/systemd/growth-os-network-heal.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now growth-os-autonomous.service
sudo systemctl enable --now growth-os-network-heal.timer
```

## Tek döngü test

```bash
python -m src.growth_os.autonomous_daemon --site turkiye-gundemi --once --status published --publish-site --enrich-images
```

## Sürekli döngü

```bash
python -m src.growth_os.autonomous_daemon --site turkiye-gundemi --status published --publish-site --enrich-images
```

## IP onarım testi

```bash
python -m src.growth_os.runtime_network --site turkiye-gundemi --publish-site
```

## VirtualBox notu

- Bridged Adapter kullanıyorsanız VM IP adresi modem/router DHCP değişikliklerinden etkilenebilir.
- NAT kullanıyorsanız public yayın için port yönlendirme gerekir.
- Bu modül IP değişimini algılar ve proje konfigürasyonunu/zone dosyalarını günceller; domain registrar tarafındaki glue/name server değişikliği gerekiyorsa bu adım hâlâ registrar panelinde yapılmalıdır.

## Güvenli üretim davranışı

Sistem kaynaklara erişemezse sahte haber üretmez. Mevcut yayınlanmış içerik korunur, hata raporu ve runtime synthesis dosyası güncellenir. Yeni haber üretimi yalnızca gerçek kaynak akışlarından yapılır.
