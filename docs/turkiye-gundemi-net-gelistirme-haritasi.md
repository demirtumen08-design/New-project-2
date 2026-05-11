# Türkiye Gündemi Net Geliştirme Haritası

Bu harita, Türkiye Gündemi sitesini haber portalı standardına taşımak için uygulanacak teknik ve editoryal adımları net sıraya koyar.

## Faz 0 - Bugün Uygulanan Kalite Kapısı

- Haber robotunun ürettiği içerik yayına çıkmadan önce kalite denetiminden geçer.
- Robotik kalıp cümle, bozuk Türkçe karakter, gelecek tarih, anlamsız/generic spot ve aşırı ince haber gövdesi tespit edilir.
- Statik site üretiminde kalite kapısı çalışır; riskli haberler siteye basılmaz.
- Admin panelinde kalite uyarı sayısı görünür.
- Panelden sorunlu yayındaki haberler tek işlemle taslağa alınabilir.

## Faz 1 - Editoryal Standart ve Arşiv Temizliği

- Başlık, spot ve gövde ayrı ayrı anlam kontrolünden geçirilecek.
- Haber metni en az iki gerçek paragraf ve somut bilgi taşıyan bir akışla kurulacak.
- Kaynaktan birebir kopyalama engellenecek; olay, kurum, kişi, yer, tarih ve rakam korunarak metin yeniden yazılacak.
- Eski arşivde kısa, tekrar eden veya robotik kalıp taşıyan haberler taslak havuzuna çekilecek.

## Faz 2 - Görsel ve Tasarım Standardı

- Her haber için ilişkili görsel zorunlu kalite alanı olacak.
- Görsel yoksa haber, görsel tamamlanana kadar düşük öncelikli yayınlanacak.
- Mobil canlı akış, kategori manşeti, reklam alanları ve dosya aboneliği düzenli kontrol edilecek.
- Görsel karanlık/boş alan sorunları için otomatik fallback kullanılacak.

## Faz 3 - SEO, Hız ve Gelir

- Kategori sayfalarında en yeni ve en güçlü haber manşete taşınacak.
- Schema, sitemap, canonical, robots ve ads.txt düzenli üretilecek.
- AdSense doğrulama kodu, reklam alanları ve dosya abonelik sayfası üretim çıktısında kalıcı tutulacak.
- Sayfa hızında görseller, CSS ve HTML çıktısı küçültme öncelikli olacak.

## Faz 4 - 7/24 Yayın Operasyonu

- Haber robotu saatlik çalışacak; önce kaynak tarayacak, sonra özgünleştirecek, ardından kalite kapısından geçirecek.
- Kalite kapısından geçmeyen içerik taslakta kalacak.
- VPS veya sabit IP'li sunucu üzerinde servis, yeniden başlatmada otomatik ayağa kalkacak.
- Günlük yedek, log ve sağlık kontrolü takip edilecek.

## Faz 5 - Ölçüm ve Büyüme

- İlk hedef: yayında güvenli ve kaliteli haber sayısını artırmak.
- İkinci hedef: kategori bazlı düzenli akış ve güçlü manşet ritmi.
- Üçüncü hedef: Google News/Discover uyumu, hızlı açılış, düşük hata oranı ve düzenli abonelik dönüşümü.

## Sürekli Kural

Kalite kapısını geçmeyen haber yayına çıkmaz. Haber robotunun görevi metin üretmek değil; anlamı korunmuş, Türkçe karakterleri doğru, kaynak metinden ayrışan ve okura gerçek bilgi veren yayın üretmektir.
