# Türkiye Gündemi App - Windows EXE Build v3

Bu paket, final haber robotunu Windows üzerinde yeniden paketlemek için hazırlanmıştır.

## Bu v3 neyi düzeltir?

- `Failed to start embedded python interpreter!` hatasına yol açabilen UPX sıkıştırması kapatıldı.
- Python seçimi 3.11/3.12 ile sınırlandı.
- Eski build çıktıları temizlenir.
- Önerilen `onedir` build yanında tek dosyalık fallback exe de üretilir.
- Exe tek başına taşınırsa oluşan hata için `onefile` alternatifi eklendi.
- Release zip artık kök `TurkiyeGundemiApp` klasörünü de içerir.

## Build

```powershell
Build-Windows-EXE.cmd
```

## Çıktılar

```text
dist\TurkiyeGundemiApp\TurkiyeGundemiApp.exe
release\TurkiyeGundemiApp-Windows-x64-folder.zip
release\TurkiyeGundemiApp-onefile.exe
release\TurkiyeGundemiApp-Windows-x64-final.zip
```

## Önemli

`TurkiyeGundemiApp.exe` dosyasını zip içinden doğrudan çalıştırmayın. Zipi tamamen ayıklayın.

Önerilen başlatma:

```text
TurkiyeGundemiApp\RUN_TurkiyeGundemiApp.cmd
```

Sorun sürerse:

```text
TurkiyeGundemiApp\DEBUG_RUN_IN_CONSOLE.cmd
```

## Uygulama özellikleri

- 7/24 haber robotu
- Otomatik yayın
- RSS kaynak cooldown/backoff yönetimi
- Her haber için kaynak sayfasından görsel tarama
- Görselleri yerel public klasöre kaydetme
- Admin panelde arşiv görsellerini tarama
