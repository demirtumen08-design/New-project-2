# Build Hotfix v4

Bu sürüm, PyInstaller 6.x ile `.spec` dosyası kullanılırken `--noupx` parametresinin hata vermesini düzeltir.

Önceki hata:

```text
ERROR: option(s) not allowed:
  --noupx
makespec options not valid when a .spec file is given
```

Düzeltme:

- `Build-Windows-EXE.ps1` içindeki `.spec` build komutlarından `--noupx` kaldırıldı.
- UPX zaten `TurkiyeGundemiApp.spec` ve `TurkiyeGundemiApp-onefile.spec` içinde `upx=False` olarak kapalıdır.

Yeniden çalıştır:

```powershell
Build-Windows-EXE.cmd
```
