# "Failed to start embedded python interpreter!" Hatası

Bu hata genellikle uygulama koduna geçmeden, PyInstaller bootloader aşamasında oluşur.

En sık nedenler:

1. EXE zip dosyasının içinden çift tıklanarak çalıştırılmıştır.
2. `TurkiyeGundemiApp.exe` tek başına kopyalanmıştır, yanındaki `_internal` klasörü yoktur.
3. Antivirüs/Defender `_internal` içindeki Python DLL dosyalarından birini karantinaya almıştır.
4. Eski build çıktısı yeni dosyalarla karışmıştır.
5. UPX ile sıkıştırılmış DLL sorun çıkarmıştır.

## Doğru çalıştırma

Önerilen kullanım:

1. `release\TurkiyeGundemiApp-Windows-x64-folder.zip` dosyasını tamamen ayıklayın.
2. Ayıklanan klasörde `TurkiyeGundemiApp\RUN_TurkiyeGundemiApp.cmd` dosyasını çalıştırın.

Doğru klasör yapısı:

```text
TurkiyeGundemiApp\
  TurkiyeGundemiApp.exe
  _internal\
  workspace\
  RUN_TurkiyeGundemiApp.cmd
  DEBUG_RUN_IN_CONSOLE.cmd
```

`_internal` yoksa exe çalışmaz.

## Tek dosya alternatifi

Bu v3 paketi ayrıca şunu üretir:

```text
release\TurkiyeGundemiApp-onefile.exe
```

Sadece tek exe taşımak istiyorsanız bu dosyayı kullanın.

## Temiz rebuild

Eski `build`, `dist`, `release`, `.venv` klasörlerini silip:

```powershell
Build-Windows-EXE.cmd
```

komutunu yeniden çalıştırın.
