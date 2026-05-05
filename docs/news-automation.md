# Türkiye Gündemi Haber Robotu

Bu entegrasyon güncel haber başlıklarını RSS/Atom kaynaklarından toplar, kaynak sayfasındaki meta açıklama ve ana paragraf sinyallerini okur, ardından Türkiye Gündemi için kaynak linkli ve editlenebilir haber taslakları üretir.

Robot tam haber metnini kopyalamak için değil, doğrulanabilir olgu cümlelerini haber diliyle yeniden düzenlemek için tasarlandı. Her haberde kaynak adı ve kaynak bağlantısı veri içinde saklanır; detay sayfasında kaynak kutusu olarak gösterilir.

## Editoryal Standart

Türkiye Gündemi haber dili Medyafaresi çizgisine yakın şekilde hızlı, açık ve doğrudan olmalıdır:

- Başlık kaynağın ana iddiasını korur; gereksiz SEO kuyrukları ve servis sayfası başlıkları yayına alınmaz.
- Spot 1-2 cümledir; olayın ne olduğunu, kimin dahil olduğunu ve ilk önemli sonucu anlatır.
- İlk paragraf başlığı tekrar etmez; doğrudan olayın ana bilgisinden başlar.
- Devam paragrafları olay, ayrıntı, açıklama ve bağlam sırasıyla ilerler.
- Türkçe karakter kullanımı zorunludur: `Türkiye`, `Gündem`, `Sözcü`, `Habertürk`, `gündem`, `dünya`, `kültür`.
- Haber gövdesinde robot, otomasyon, JSON, panel veya sistem işleyişi anlatılmaz.
- Çok kısa, bozuk kodlamalı, hukuki ilan/servis sayfası niteliğindeki veya yalnızca arama trafiği için yazılmış içerikler taslakta tutulur.
- Paragraflar anlamlı cümle akışıyla kurulur; kırık alıntılar, büyük harf bölüm başlıkları ve yarım cümleler temizlenir.

## Kaynaklar

Kaynak listesi `config/news_sources.json` dosyasındadır. Başlangıç kaynakları:

- TRT Haber RSS akışlarından son dakika, gündem, Türkiye, ekonomi, dünya, spor ve teknoloji.
- NTV son dakika RSS akışı.
- Sözcü son dakika, gündem ve ekonomi akışları.
- Cumhuriyet, Habertürk ve Ensonhaber genel/gündem akışları.
- Medyafaresi RSS akışı.

Yeni kaynak eklemek için bu dosyaya `enabled`, `name`, `url` ve `category` alanlarıyla yeni kayıt eklemek yeterlidir. Kaynak çıkarma işlemi için `enabled` değeri `false` yapılabilir.

## Panelden Kullanma

Admin panelinde `Haber Robotu` sekmesi:

1. `Kaynakları Tara` ile güncel akışı getirir.
2. `Haberleri İçeriğe Al` ile yeni haberleri JSON içeriğe ekler.
3. Durum `Yayında` ve `İçeriğe aldıktan sonra siteyi yayınla` işaretliyse kalite kapısından geçen haberler statik siteye yansır.
4. Kalite kapısından geçmeyen haberler otomatik olarak taslakta kalır.
5. Durum `Taslak` seçilirse haberler sitede görünmez, yalnızca panelde kalır.

## Komut Satırı

Sadece tarama:

```bash
python -m src.growth_os.news_automation --scan-only --limit 12
```

Taslak içeri aktar:

```bash
python -m src.growth_os.news_automation --limit 12 --max-items 3 --status draft
```

Yayına al ve statik siteyi yeniden üret:

```bash
python -m src.growth_os.news_automation --limit 12 --max-items 1 --status published --publish-site
```

## Otomatik Zamanlayıcı

Linux sunucuda timer dosyaları hazırdır:

```bash
sudo cp ops/systemd/growth-os-newsbot.service /etc/systemd/system/
sudo cp ops/systemd/growth-os-newsbot.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now growth-os-newsbot.timer
```

Varsayılan timer `--status published --publish-site` ile çalışır. Tam otomatik yayın istenmiyorsa service dosyasında bunu `--status draft` olarak değiştirin.
