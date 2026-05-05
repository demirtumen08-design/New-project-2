# turkiyegundemi.com Canli Domain Tasima

## Mevcut Durum

- Model B yerel panel: `http://127.0.0.1/admin`
- Public IPv4: `176.88.74.65`
- Windows LAN IPv4: `192.168.1.30`
- Domain delegasyonu su an `andy.ns.cloudflare.com` ve `gina.ns.cloudflare.com` uzerinde gorunuyor.
- Cloudflare bu zone icin authoritative cevap vermiyor; bu nedenle domain su an DNS tarafinda cozulmuyor.

## Gerekli DNS Kayitlari

Cloudflare veya Natro DNS panelinde asagidaki kayitlar bulunmali:

| Type | Name | Value | Proxy |
| --- | --- | --- | --- |
| A | `@` | `176.88.74.65` | DNS only |
| A | `www` | `176.88.74.65` | DNS only |

Natro DNS kullanilacaksa nameserver'lar:

- `ns1.natrohost.com`
- `ns2.natrohost.com`

Cloudflare kullanilacaksa once domain Cloudflare hesabinda aktif zone olarak eklenmeli ve atanan nameserver'lar Natro panelindeki nameserver'larla birebir ayni olmali. Mevcut nameserver'lar Cloudflare tarafinda authoritative cevap vermedigi icin bu haliyle calismaz.

## Modem Port Yonlendirme

Modem/router panelinde:

- TCP `80`  -> `192.168.1.30`
- TCP `443` -> `192.168.1.30`

Bilgisayarin IP'si degisirse bu yonlendirme bozulur. Modemde DHCP reservation ile `192.168.1.30` sabitlenmelidir.

## Windows/WSL Port Koprusu

Yonetici PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File ".\tools\expose_model_b_to_domain.ps1"
```

Bu script Windows firewall kuralini ve `netsh interface portproxy` koprusunu kurar.

## SSL

DNS ve portlar calistiktan sonra:

```bash
wsl -d Ubuntu -- sudo certbot --nginx -d turkiyegundemi.com -d www.turkiyegundemi.com
```

SSL alinmadan once domainin `176.88.74.65` IP'sine cozulmesi ve 80 portunun internetten acik olmasi gerekir.
