# Bu Bilgisayarda Sanal Linux Sunucu Kurulumu

Bu rehber, Turkiye Gundemi Model B sistemini bu Windows bilgisayarda bir Linux sanal ortaminda calistirmak icindir.

## Onemli Sinir

Bu yontem bilgisayar acikken calisir. Bilgisayar kapanirsa site, admin ve DNS kapanir. 7/24 yayin icin VPS/VDS veya ayri surekli acik mini server gerekir.

## Secenek 1: WSL2 Ubuntu VM

En hizli yoldur. Windows Home ile uyumludur.

Ilk asama:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_wsl_ubuntu_vm.ps1
```

Bu komut yonetici onayi ister ve Windows sanallastirma ozelliklerini acar. Sonra Windows'u yeniden baslatin.

Yeniden baslatmadan sonra:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\provision_wsl_model_b.ps1
```

WSL hazir olunca:

```text
Site:  http://127.0.0.1/
Admin: http://127.0.0.1/admin
```

WSL2 uzerinde yerel admin ve site testi icin klasik NAT + `localhostForwarding=true` kullanilir. Bu bilgisayarda stabil yerel adres `http://127.0.0.1/` ve admin adresi `http://127.0.0.1/admin` olarak kabul edilir.

DNS icin uretim notu: WSL2, Windows'un DNS/53 port katmani nedeniyle authoritative DNS icin guvenilir hedef degildir. BIND zone dosyalari uretilebilir ve servis kurulabilir; fakat public authoritative DNS icin bridged VirtualBox VM, ayri Linux mini server veya public Linux sunucu tercih edilmelidir.

## Secenek 2: VirtualBox Ubuntu VM

Modem port yonlendirme icin daha temizdir; cunku bridged network ile VM ic agda ayri bir cihaz gibi gorunur.

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_virtualbox_ubuntu_shell.ps1
```

Bu script VirtualBox kurar, Ubuntu Server ISO indirir ve VM kabugunu hazirlar. Ubuntu kurulum ekraninda:

- 2 CPU / 4 GB RAM / 40 GB disk hazirdir.
- Network bridged olmalidir.
- Ubuntu icinde sabit LAN IP verin.
- Kurulumdan sonra proje dosyalarini VM'e kopyalayip Model B scriptlerini calistirin.

## Hangisini Secelim?

- Hizli test: WSL2
- Modemden public port yonlendirme ve DNS: VirtualBox veya ayri Linux mini server
- 7/24 canli yayin: VPS/VDS
