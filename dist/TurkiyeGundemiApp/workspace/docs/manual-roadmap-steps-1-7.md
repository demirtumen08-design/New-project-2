# Türkiye Gündemi Manuel Yol Haritası: 1-7 Entegrasyon Durumu

Bu dosya, ilk manuel yol haritasındaki 1-7 arasındaki adımların mevcut sisteme nasıl işlendiğini özetler.

## 1. Çalışan Durumu Sabitleme

- Mevcut Türkiye Gündemi sistemi çalışan prototip olarak korunur.
- Haber robotu, site jeneratörü, admin paneli ve Windows EXE paketi aynı çalışma alanını kullanır.
- Statik site çıktısı `sites/turkiye-gundemi/public` altında üretilir.

## 2. Haber Robotu Editoryal Testi

- Admin panelindeki `Haber Robotu` sekmesi kaynak tarama, haber içeriğe alma ve otonom döngü testi için kullanılabilir.
- Robot; başlık, spot, paragraf bütünlüğü, Türkçe karakter, kaynak bağlantısı ve yayın kalitesi kapısını birlikte kontrol eder.
- Kalite kapısından geçemeyen haberler `draft` durumuna düşer.

## 3. Yayın Standardı

- Yayın standardı `docs/news-automation.md` dosyasına işlendi.
- İlk paragraf başlığı tekrar etmez; haberin ana bilgisini verir.
- Devam paragrafları ayrıntı, bağlam ve son durum sırasıyla ilerler.
- Robot, otomasyon, JSON veya panel metni haber gövdesine sızamaz.

## 4. Kaynak Listesi

Kaynak havuzu `config/news_sources.json` içinden yönetilir. Aktif kaynaklar arasında TRT Haber, NTV, Sözcü, Cumhuriyet, Habertürk, Ensonhaber, Medyafaresi, Diken, BirGün, Independent Türkçe, Dünya Gazetesi ve BBC Türkçe bulunur.

T24 için RSS endpoint doğrulanamadığı için kaynak kaydı şimdilik pasif bırakıldı. Uygun ve stabil RSS/Atom adresi bulununca `enabled` değeri `true` yapılabilir.

## 5. Site Yapısı

Statik site jeneratörü artık şu kurumsal sayfaları otomatik üretir:

- `/hakkimizda/`
- `/kunye/`
- `/iletisim/`
- `/gizlilik-politikasi/`

Bu sayfalar sitemap içine de eklenir. Yayın öncesinde künye ve iletişim bilgilerinin gerçek kurumsal bilgilerle tamamlanması gerekir.

## 6. Güvenli Yayına Geçiş Hazırlığı

Zip paketindeki runtime network bileşeni sisteme alındı; ancak canlı IP/DNS değiştirme varsayılan olarak kapalıdır. Bu sayede statik IP işlemi tamamlanmadan sistem ağ kayıtlarını otomatik değiştirmez.

Statik IP hazır olduğunda:

- Natro DNS A kayıtları statik IP'ye yönlendirilir.
- Modemde yalnızca 80 ve 443 portları açılır.
- Admin paneli doğrudan internete açık bırakılmaz.
- HTTPS sertifikası kurulur.

## 7. Yayın Akışı Modeli

Varsayılan model:

- Haberler kaynaklardan otomatik taranır.
- Kalite kapısından geçenler yayına alınabilir.
- Riskli, kısa, servis/ilan/arama sayfası niteliğindeki içerikler taslakta kalır.
- Kaynak görseli indirme telif kontrolü gerektirdiği için varsayılan olarak kapalıdır; panelden manuel açılabilir.
- Otonom döngü bileşeni kuruldu, tek seferlik test ve servis olarak çalıştırma dokümante edildi.
