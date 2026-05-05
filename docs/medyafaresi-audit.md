# Medyafaresi.com Derin Analiz ve Yol Haritasi

Analiz tarihi: 4 Mayis 2026. Bu rapor, canli HTTP/HTML olcumleri, sitemap incelemesi ve halka acik Similarweb Mart 2026 verileri temel alinarak hazirlandi.

## Yonetici Ozeti

Medyafaresi'nin temel problemi tek bir teknik hata degil; marka gucu, sitemap mimarisi, sayfa agirligi, dagitim kaslari ve editoriyal odak birlikte dusuk kalmis. Rakipler dogrudan trafik ve organik aramada guclu marka hafizasina sahipken Medyafaresi daha dar bir kategori algisina sikismis gorunuyor: medya, magazin, reyting.

Ilk 90 gunluk hedef 500 bin bandindan 1,5-2 milyon aylik izlenime cikmak olmali. 12 ay hedefi, dogru ekip ve yayin temposu ile 5 milyon+ izlenim. Bunun icin teknik indeksleme, hiz, haber uretim ritmi, kategori hub'lari ve sosyal/Google News dagitimi birlikte ele alinmali.

## Canli Teknik Bulgular

| Sinyal | Medyafaresi | T24 | Sozcu | Yorum |
| --- | ---: | ---: | ---: | --- |
| Ana sayfa HTML | 331 KB | 312 KB | 268 KB | Medyafaresi rakiplerden agir; hedef 180-220 KB |
| Ana sayfa script | 34 | 60 | 22 | Medyafaresi orta riskte; bloklayici script sayisi dusurulmeli |
| Ana sayfa gorsel | 48 | 211 | 126 | Gorsel sayisi makul, ama responsive `srcset` yok |
| Makale HTML | 291 KB | 181 KB | 131 KB | Medyafaresi makale sayfasi cok agir |
| Makale script | 39 | 63 | 25 | Reklam ve etiket yonetimi sadelelestirilmeli |
| Genel sitemap | 250 URL | sitemap index | aylik index | Medyafaresi archive/index sitemap yapisinda zayif |
| News sitemap | 56 URL | var | 504 URL | Medyafaresi son 48 saat kapasitesini daha iyi doldurmali |
| Cache header | `max-age=60, no-store` | `no-cache, private` | `public, max-age=60` | `no-store` tarayici cache ve ara katmanlar icin ters sinyal |

## Rakip Kiyaslamasi

Similarweb Mart 2026 verilerine gore T24 toplam ziyarette 19,4M seviyesinde, bounce rate %50,73, sayfa/ziyaret 2,64 ve ortalama ziyaret 1:46. Sozcu icin dogrudan trafik %66,83; T24 icin dogrudan trafik %60,54. Bu, iki rakibin de yalnizca Google'a degil marka aliskanligina dayali trafik aldigini gosteriyor.

Medyafaresi'nin 500 bin civari izlenim bandindan cikmasi icin sadece SEO degil, "her gun geri gelme sebebi" uretmesi gerekiyor. Rakiplerin gucu:

- Net marka aramasi ve dogrudan ziyaret.
- Geniş sitemap/archive mimarisi.
- Siyasi gundem, ekonomi, son dakika ve yazar/analiz katmanlarinda surekli akış.
- Sosyal dagitim ve bildirim refleksi.

## Noksanlar

1. Sitemap kapsami dar: robots.txt cok sayida sitemap bildiriyor ama ana genel sitemap 250 URL, news sitemap 56 URL. Arsiv, kategori, yazar ve aylik/yillik sitemap index kurgusu rakip standardinda degil.
2. Makale sayfasi agir: 291 KB HTML ve 39 script, haber okuma deneyimini ve mobil hiz algisini zayiflatiyor.
3. Cache stratejisi net degil: `no-store` ile Cloudflare `HIT` birlikte gorunuyor. Edge cache, browser cache ve CMS purge ayri tasarlanmali.
4. Responsive image eksigi: Ana gorsellerde `srcset/sizes` yok; mobilde fazla buyuk gorsel inebilir.
5. Editoriyal kategori pozisyonu dar: Reyting/magazin gucu korunurken gundem, ekonomi, yasam, saglik ve teknoloji hub'lari derinlestirilmeli.
6. Marka sadakati dusuk: Rakiplerde direct trafik ana kanal. Medyafaresi icin bildirim, bulten, sosyal seri ve "her gun bakilan sayfa" ihtiyaci var.
7. Yazar/konu otoritesi zayif gorunuyor: Author page, konu hub'i, kaynak sayfasi ve evergreen dosya yapisi buyutulmeli.

## 90 Gunluk Yol Haritasi

### 0-14 Gun: Teknik Temel

- Sitemap index kur: `sitemap.xml` bir index olmali; aylik haber sitemapleri, kategori sitemapleri, yazar sitemapleri ve news sitemap ayrilmali.
- News sitemap'i son 48 saat haberleriyle otomatik guncelle; eski URL'leri news metadata'dan cikar.
- Makale HTML'ini 160 KB altina indir; tekrar eden inline bloklari ve gereksiz server-side payload'i azalt.
- Reklam scriptlerini consent, lazy slot ve viewport tetikli yukleme ile sadeleştir.
- `Cache-Control` politikasini ayir: HTML icin kisa edge cache + stale-while-revalidate; statik varliklar icin uzun immutable cache.
- Her makalede NewsArticle JSON-LD, BreadcrumbList, author, datePublished/dateModified, image 16:9/4:3/1:1 alanlarini standartlastir.

### 15-45 Gun: Editoriyal Buyume

- "Son Dakika", "Gundem", "Ekonomi", "Reyting Sonuclari", "TV Dizileri", "Medya Kulisleri" hub sayfalari olustur.
- Her hub icin kalici aciklama, en son haber akisi, en cok okunan, ilgili etiket ve evergreen rehber bloklari ekle.
- Reyting sonuclari kategorisini veri urunune cevir: gunluk tablo, kanal/dizi arsivi, haftalik analiz, schema destekli sayfalar.
- Gunde 40-60 kisa haber yerine 20-30 daha iyi paketlenmis haber + 5 analiz/dosya hedefle.
- Baslik standardi: merak uyandir ama arama niyetini kapat; "kim, ne, ne zaman" bilgisini saklama.

### 46-90 Gun: Dagitim ve Sadakat

- Web push ve e-posta bulteni kur; kategorilere gore abonelik.
- Google News Publisher Center, Search Console, Discover performansi haftalik takip.
- Sosyal paketleme: her haber icin X/Facebook/Instagram/YouTube Shorts kisa metinleri ve gorsel oranlari uret.
- Ic link otomasyonu: her haber yayininda ayni kategori, ayni kisi, ayni konu ve evergreen hub linkleri ekle.
- A/B test: ana sayfa siralama, baslik, thumbnail, son dakika bandi ve haber kart formati.

## 12 Aylik Hedef Mimari

- Medyafaresi: mevcut CMS uzerine audit + sitemap + schema + performans adaptorleri.
- Turkiye Gundemi: statik-first, self-hosted, JSON/Markdown/SQLite kaynakli yeni nesil haber portali.
- Ortak Growth OS: iki siteyi ayni kurallarla olcer, raporlar, site haritasi uretir, teknik regresyonlari yakalar.
- Kendi hosting: Linux sunucu, Nginx veya Caddy, Python servisleri, SQLite/PostgreSQL, object storage alternatifi olarak yerel disk + yedekleme.

## Uygulama Notu

Bu repo ilk iskeleti kurar. Medyafaresi uzerinde otomatik uygulama icin CMS kaynak kodu, deploy yetkisi ve sunucu erisimi gerekir. O erisim geldiginde buradaki audit kurallari patch/adaptor katmanina baglanabilir.

Turkiye Gundemi tarafi artik yalnizca prototip degil; admin panelinden haber ve site ayari duzenlenebilen, yayinlandiginda statik HTML, sitemap, news sitemap, robots.txt ve llms.txt ureten bir site iskeletidir.
