from __future__ import annotations

import json
import re
import unicodedata
import email.utils
import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_site, project_path


TR_MAP = str.maketrans(
    {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
        "Ç": "c",
        "Ğ": "g",
        "İ": "i",
        "I": "i",
        "Ö": "o",
        "Ş": "s",
        "Ü": "u",
    }
)

MOJIBAKE_REPLACEMENTS = {
    "Ãƒâ€¡": "Ç",
    "ÃƒÂ§": "ç",
    "ÃƒÄ": "Ğ",
    "Ã„Å¸": "ğ",
    "Ã„Å¾": "Ğ",
    "ÃƒÅ“": "Ü",
    "ÃƒÂ¼": "ü",
    "Ãƒâ€“": "Ö",
    "ÃƒÂ¶": "ö",
    "Ã…Å¾": "Ş",
    "Ã…Å¸": "ş",
    "Ã„Â°": "İ",
    "Ã„Â±": "ı",
    "Ã‡": "Ç",
    "Ã§": "ç",
    "ÄŸ": "ğ",
    "Äž": "Ğ",
    "Ä±": "ı",
    "Ä°": "İ",
    "Ã–": "Ö",
    "Ã¶": "ö",
    "Åž": "Ş",
    "ÅŸ": "ş",
    "Ãœ": "Ü",
    "Ã¼": "ü",
    "â€œ": '"',
    "â€": '"',
    "â€™": "'",
    "â€“": "-",
    "â€”": "-",
    "â€¦": "...",
    "ï¿½": "",
}

COMMON_TURKISH_REPAIRS = {
    "Turkiye": "Türkiye",
    "turkiye": "Türkiye",
    "TURKIYE": "TÜRKİYE",
    "Turk": "Türk",
    "turk": "Türk",
    "Turkce": "Türkçe",
    "turkce": "Türkçe",
    "Gundem": "Gündem",
    "gundem": "gündem",
    "Gundemi": "Gündemi",
    "gundemi": "gündemi",
    "Dunya": "Dünya",
    "dunya": "dünya",
    "Kultur": "Kültür",
    "kultur": "kültür",
    "Sozcu": "Sözcü",
    "sozcu": "Sözcü",
    "Cumhurbaskani": "Cumhurbaşkanı",
    "cumhurbaskani": "cumhurbaşkanı",
    "Cumhurbaskanligi": "Cumhurbaşkanlığı",
    "cumhurbaskanligi": "cumhurbaşkanlığı",
    "baskan": "başkan",
    "Baskan": "Başkan",
    "baskani": "başkanı",
    "Baskani": "Başkanı",
    "secim": "seçim",
    "Secim": "Seçim",
    "secilen": "seçilen",
    "Secilen": "Seçilen",
    "sorusturma": "soruşturma",
    "Sorusturma": "Soruşturma",
    "yurutulen": "yürütülen",
    "Yurutulen": "Yürütülen",
    "goruldu": "görüldü",
    "Goruldu": "Görüldü",
    "gorusme": "görüşme",
    "Gorusme": "Görüşme",
    "gozalti": "gözaltı",
    "Gozalti": "Gözaltı",
    "gozaltina": "gözaltına",
    "Gozaltina": "Gözaltına",
    "aciklama": "açıklama",
    "Aciklama": "Açıklama",
    "aciklamasi": "açıklaması",
    "Aciklamasi": "Açıklaması",
    "acikladi": "açıkladı",
    "Acikladi": "Açıkladı",
    "aciklandi": "açıklandı",
    "Aciklandi": "Açıklandı",
    "yapti": "yaptı",
    "Yapti": "Yaptı",
    "yapildi": "yapıldı",
    "Yapildi": "Yapıldı",
    "yapilan": "yapılan",
    "Yapilan": "Yapılan",
    "yapilacak": "yapılacak",
    "Yapilacak": "Yapılacak",
    "cikti": "çıktı",
    "Cikti": "Çıktı",
    "cikan": "çıkan",
    "Cikan": "Çıkan",
    "iliskin": "ilişkin",
    "Iliskin": "İlişkin",
    "bugun": "bugün",
    "Bugun": "Bugün",
    "dun": "dün",
    "Dun": "Dün",
    "sonuc": "sonuç",
    "Sonuc": "Sonuç",
    "sonuclandi": "sonuçlandı",
    "Sonuclandi": "Sonuçlandı",
    "kuresel": "küresel",
    "Kuresel": "Küresel",
    "buyuk": "büyük",
    "Buyuk": "Büyük",
    "kucuk": "küçük",
    "Kucuk": "Küçük",
    "ulke": "ülke",
    "Ulke": "Ülke",
    "ulkenin": "ülkenin",
    "Ulkenin": "Ülkenin",
    "sehir": "şehir",
    "Sehir": "Şehir",
    "sehit": "şehit",
    "Sehit": "Şehit",
    "universite": "üniversite",
    "Universite": "Üniversite",
    "ogrenci": "öğrenci",
    "Ogrenci": "Öğrenci",
    "ogretmen": "öğretmen",
    "Ogretmen": "Öğretmen",
    "egitimde": "eğitimde",
    "Egitimde": "Eğitimde",
    "saglik": "sağlık",
    "Saglik": "Sağlık",
    "egitim": "eğitim",
    "Egitim": "Eğitim",
    "guvenlik": "güvenlik",
    "Guvenlik": "Güvenlik",
    "guvenligi": "güvenliği",
    "Guvenligi": "Güvenliği",
    "suc": "suç",
    "Suc": "Suç",
    "suclama": "suçlama",
    "Suclama": "Suçlama",
    "savci": "savcı",
    "Savci": "Savcı",
    "baslik": "başlık",
    "Baslik": "Başlık",
    "basligi": "başlığı",
    "Basligi": "Başlığı",
    "yayin": "yayın",
    "Yayin": "Yayın",
    "yayinda": "yayında",
    "Yayinda": "Yayında",
    "yayinlandi": "yayınlandı",
    "Yayinlandi": "Yayınlandı",
    "yayimlandi": "yayımlandı",
    "Yayimlandi": "Yayımlandı",
    "yayini": "yayını",
    "Yayini": "Yayını",
    "yayinlari": "yayınları",
    "Yayinlari": "Yayınları",
    "duzenleme": "düzenleme",
    "Duzenleme": "Düzenleme",
    "duzenlendi": "düzenlendi",
    "Duzenlendi": "Düzenlendi",
    "donem": "dönem",
    "Donem": "Dönem",
    "onemli": "önemli",
    "Onemli": "Önemli",
    "oncesi": "öncesi",
    "Oncesi": "Öncesi",
    "sonrasi": "sonrası",
    "Sonrasi": "Sonrası",
    "gelisme": "gelişme",
    "Gelisme": "Gelişme",
    "gelismeler": "gelişmeler",
    "Gelismeler": "Gelişmeler",
    "gundemde": "gündemde",
    "Gundemde": "Gündemde",
    "gundemine": "gündemine",
    "Gundemine": "Gündemine",
    "icerik": "içerik",
    "Icerik": "İçerik",
    "icerige": "içeriğe",
    "Icerige": "İçeriğe",
    "dosya": "dosya",
    "Dosya": "Dosya",
    "dergi": "dergi",
    "Dergi": "Dergi",
    "ozel": "özel",
    "Ozel": "Özel",
    "ozgur": "özgür",
    "Ozgur": "Özgür",
    "ozgurluk": "özgürlük",
    "Ozgurluk": "Özgürlük",
    "kamuoyu": "kamuoyu",
    "Kamuoyu": "Kamuoyu",
    "kisi": "kişi",
    "Kisi": "Kişi",
    "kisiler": "kişiler",
    "Kisiler": "Kişiler",
    "calisma": "çalışma",
    "Calisma": "Çalışma",
    "calismasi": "çalışması",
    "Calismasi": "Çalışması",
    "calisiyor": "çalışıyor",
    "Calisiyor": "Çalışıyor",
    "cagri": "çağrı",
    "Cagri": "Çağrı",
    "cagrisi": "çağrısı",
    "Cagrisi": "Çağrısı",
    "cozum": "çözüm",
    "Cozum": "Çözüm",
    "savas": "savaş",
    "Savas": "Savaş",
    "baris": "barış",
    "Baris": "Barış",
    "seviye": "seviye",
    "Seviye": "Seviye",
    "yuksek": "yüksek",
    "Yuksek": "Yüksek",
    "dusuk": "düşük",
    "Dusuk": "Düşük",
    "artis": "artış",
    "Artis": "Artış",
    "dusus": "düşüş",
    "Dusus": "Düşüş",
    "piyasa": "piyasa",
    "Piyasa": "Piyasa",
    "ekonomik": "ekonomik",
    "Ekonomik": "Ekonomik",
    "bolge": "bölge",
    "Bolge": "Bölge",
    "bolgesinde": "bölgesinde",
    "Bolgesinde": "Bölgesinde",
    "koy": "köy",
    "Koy": "Köy",
    "koyde": "köyde",
    "Koyde": "Köyde",
    "karsi": "karşı",
    "Karsi": "Karşı",
    "karsisinda": "karşısında",
    "Karsisinda": "Karşısında",
    "yonelik": "yönelik",
    "Yonelik": "Yönelik",
    "gore": "göre",
    "Gore": "Göre",
    "soyledi": "söyledi",
    "Soyledi": "Söyledi",
    "suruyor": "sürüyor",
    "Suruyor": "Sürüyor",
    "sure": "süre",
    "Sure": "Süre",
    "hafta sonu": "hafta sonu",
    "IHA": "İHA",
    "SIHA": "SİHA",
}


# Encoding-safe text tables. Keeping these bindings close to their use prevents
# Windows/WSL console encoding drift from damaging Turkish character handling.
TR_MAP = str.maketrans(
    {
        "\u00e7": "c",
        "\u011f": "g",
        "\u0131": "i",
        "\u00f6": "o",
        "\u015f": "s",
        "\u00fc": "u",
        "\u00c7": "c",
        "\u011e": "g",
        "\u0130": "i",
        "I": "i",
        "\u00d6": "o",
        "\u015e": "s",
        "\u00dc": "u",
    }
)

MOJIBAKE_REPLACEMENTS = {
    "\u00c3\u00a7": "\u00e7",
    "\u00c4\u0178": "\u011f",
    "\u00c4\u017e": "\u011e",
    "\u00c4\u00b1": "\u0131",
    "\u00c4\u00b0": "\u0130",
    "\u00c3\u00b6": "\u00f6",
    "\u00c3\u2013": "\u00d6",
    "\u00c5\u0178": "\u015f",
    "\u00c5\u017e": "\u015e",
    "\u00c3\u00bc": "\u00fc",
    "\u00c3\u0153": "\u00dc",
    "\u00e2\u20ac\u0153": '"',
    "\u00e2\u20ac\u009d": '"',
    "\u00e2\u20ac\u2122": "'",
    "\u00e2\u20ac\u201c": "-",
    "\u00e2\u20ac\u201d": "-",
    "\u00e2\u20ac\u00a6": "...",
    "\ufffd": "",
}

COMMON_TURKISH_REPAIRS.update(
    {
        "Turkiye": "T\u00fcrkiye",
        "turkiye": "T\u00fcrkiye",
        "TURKIYE": "T\u00dcRK\u0130YE",
        "Gundem": "G\u00fcndem",
        "gundem": "g\u00fcndem",
        "Gundemi": "G\u00fcndemi",
        "gundemi": "g\u00fcndemi",
        "Cumhurbaskani": "Cumhurba\u015fkan\u0131",
        "cumhurbaskani": "cumhurba\u015fkan\u0131",
        "Cumhurbaskanligi": "Cumhurba\u015fkanl\u0131\u011f\u0131",
        "cumhurbaskanligi": "cumhurba\u015fkanl\u0131\u011f\u0131",
        "aciklama": "a\u00e7\u0131klama",
        "Aciklama": "A\u00e7\u0131klama",
        "acikladi": "a\u00e7\u0131klad\u0131",
        "Acikladi": "A\u00e7\u0131klad\u0131",
        "aciklandi": "a\u00e7\u0131kland\u0131",
        "Aciklandi": "A\u00e7\u0131kland\u0131",
        "bugun": "bug\u00fcn",
        "Bugun": "Bug\u00fcn",
        "yayin": "yay\u0131n",
        "Yayin": "Yay\u0131n",
        "yayini": "yay\u0131n\u0131",
        "Yayini": "Yay\u0131n\u0131",
        "yayinda": "yay\u0131nda",
        "Yayinda": "Yay\u0131nda",
        "yayinlandi": "yay\u0131nland\u0131",
        "Yayinlandi": "Yay\u0131nland\u0131",
        "yayimlandi": "yay\u0131mland\u0131",
        "Yayimlandi": "Yay\u0131mland\u0131",
        "kisi": "ki\u015fi",
        "Kisi": "Ki\u015fi",
        "kisiler": "ki\u015filer",
        "Kisiler": "Ki\u015filer",
        "IHA": "\u0130HA",
        "SIHA": "S\u0130HA",
    }
)

TURKISH_CHARS = "\u00e7\u011f\u0131\u00f6\u015f\u00fc\u00c7\u011e\u0130\u00d6\u015e\u00dc"
MOJIBAKE_MARKERS = ("\u00c3", "\u00c4", "\u00c5", "\u00e2\u20ac", "\ufffd")
TURKISH_UPPERCASE = "A-Z\u00c7\u011e\u0130\u00d6\u015e\u00dc"


def slugify(value: str) -> str:
    cleaned = value.translate(TR_MAP)
    cleaned = unicodedata.normalize("NFKD", cleaned).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", cleaned).strip("-").lower()
    return cleaned or "haber"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def turkish_text_score(value: str) -> int:
    text = str(value or "")
    good = sum(text.count(char) for char in TURKISH_CHARS)
    bad = sum(text.count(marker) for marker in MOJIBAKE_MARKERS)
    return good - (bad * 4)


def repair_mojibake(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if any(marker in text for marker in MOJIBAKE_MARKERS):
        for encoding in ("latin1", "cp1252", "cp1254"):
            try:
                fixed = text.encode(encoding, errors="ignore").decode("utf-8", errors="ignore")
            except Exception:
                continue
            if fixed and turkish_text_score(fixed) > turkish_text_score(text):
                text = fixed
                break
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text


def restore_common_turkish(value: str) -> str:
    text = value
    for bad, good in sorted(COMMON_TURKISH_REPAIRS.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(rf"\b{re.escape(bad)}\b", good, text)
    return text


def clean_article_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = repair_mojibake(text)
    text = restore_common_turkish(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\b(\d{1,2})\.\s+(\d{2})\b", r"\1.\2", text)
    text = re.sub(r"\b(\d+),\s+(\d+)\b", r"\1,\2", text)
    text = re.sub(r"\b(\d+)\.\s+(\d+)\b", r"\1.\2", text)
    text = re.sub(rf"(?<=[.!?])(?=[{TURKISH_UPPERCASE}])", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;])(?=\S)", r"\1 ", text)
    text = re.sub(r"\b(\d+),\s+(\d+)\b", r"\1,\2", text)
    text = re.sub(r"\b(\d+)\.\s+(\d+)\b", r"\1.\2", text)
    text = re.sub(r"([.!?]){3,}", "...", text)
    text = re.sub(r"([!?])\1+", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clamp_iso_datetime(value: Any, fallback: str | None = None) -> str:
    text = str(value or fallback or now_iso()).strip()
    now = datetime.now(timezone.utc).astimezone()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        try:
            parsed = email.utils.parsedate_to_datetime(text)
        except Exception:
            return fallback or now.isoformat(timespec="seconds")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone()
    if parsed > now:
        parsed = now
    return parsed.isoformat(timespec="seconds")


def article_path(site_id: str) -> Path:
    site = get_site(site_id)
    return project_path(site["content_file"])


def load_articles(site_id: str) -> list[dict[str, Any]]:
    path = article_path(site_id)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        articles = json.load(handle)
    return sorted(articles, key=lambda item: item.get("published_at", ""), reverse=True)


def save_articles(site_id: str, articles: list[dict[str, Any]]) -> None:
    path = article_path(site_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(articles, key=lambda item: item.get("published_at", ""), reverse=True)
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_article(raw: dict[str, Any], existing_slug: str | None = None) -> dict[str, Any]:
    title = clean_article_text(raw.get("title", ""))
    if not title:
        raise ValueError("Baslik zorunlu.")
    slug = str(raw.get("slug") or existing_slug or slugify(title)).strip()
    slug = slugify(slug)
    body_value = raw.get("body", [])
    if isinstance(body_value, str):
        body = [clean_article_text(part) for part in re.split(r"\n\s*\n", body_value) if clean_article_text(part)]
    else:
        body = [clean_article_text(part) for part in body_value if clean_article_text(part)]
    if not body:
        body = [clean_article_text(raw.get("summary", "")) or title]
    tags_value = raw.get("tags", [])
    if isinstance(tags_value, str):
        tags = [clean_article_text(part) for part in tags_value.split(",") if clean_article_text(part)]
    else:
        tags = [clean_article_text(part) for part in tags_value if clean_article_text(part)]
    published_at = clamp_iso_datetime(raw.get("published_at") or now_iso())
    modified_at = clamp_iso_datetime(raw.get("modified_at") or now_iso())
    image = str(raw.get("image") or "/assets/images/ankara.png").strip()
    if not image.startswith("/") and not image.startswith("http"):
        image = "/" + image
    status = str(raw.get("status") or "published").strip()
    if status not in {"draft", "published"}:
        status = "published"
    article = {
        "slug": slug,
        "category": str(raw.get("category") or "gundem").strip(),
        "title": title,
        "summary": clean_article_text(raw.get("summary") or title),
        "body": body,
        "author": clean_article_text(raw.get("author") or "Türkiye Gündemi Haber Merkezi"),
        "published_at": published_at,
        "modified_at": modified_at,
        "image": image,
        "image_alt": clean_article_text(raw.get("image_alt") or title),
        "tags": tags,
        "status": status,
    }
    date_metadata = {"source_published_at", "imported_at", "image_enriched_at", "originality_checked_at"}
    raw_metadata = {"source_url", "source_feed", "source_title", "automation_signature", "image_source_url"}
    numeric_metadata = {"news_score", "quality_score", "word_count", "fact_count", "source_count", "source_copy_flags"}
    for key in (
        "source_name",
        "source_url",
        "source_title",
        "source_feed",
        "source_published_at",
        "automation_signature",
        "imported_at",
        "image_source_url",
        "image_provider",
        "image_enriched_at",
        "news_score",
        "quality_score",
        "word_count",
        "fact_count",
        "source_count",
        "source_copy_flags",
        "title_meaning_ok",
        "article_meaning_ok",
        "editorial_profile",
        "editorial_policy",
        "originality_checked_at",
        "publish_decision",
        "quality_flags",
        "attachment_url",
        "issue_number",
        "cover_label",
        "premium_required",
        "subscription_price",
        "subscription_tier",
    ):
        if raw.get(key):
            if key in date_metadata:
                article[key] = clamp_iso_datetime(raw.get(key), fallback=published_at)
            elif key == "premium_required":
                value = str(raw.get(key)).strip().casefold()
                article[key] = "false" if value in {"0", "false", "hayır", "hayir", "no", "free", "ücretsiz", "ucretsiz"} else "true"
            elif key in raw_metadata or key in numeric_metadata or key == "attachment_url":
                article[key] = str(raw.get(key)).strip()
            else:
                article[key] = clean_article_text(raw.get(key))
    related_sources = raw.get("related_sources")
    if isinstance(related_sources, list):
        article["related_sources"] = [clean_article_text(item) for item in related_sources if clean_article_text(item)]
    return article


def upsert_article(site_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    articles = load_articles(site_id)
    incoming_slug = str(raw.get("slug") or "").strip()
    existing = next((item for item in articles if item.get("slug") == incoming_slug), None)
    article = normalize_article(raw, incoming_slug or None)
    article["modified_at"] = now_iso()
    updated = False
    for index, item in enumerate(articles):
        if item.get("slug") == incoming_slug or item.get("slug") == article["slug"]:
            if existing:
                article["published_at"] = clamp_iso_datetime(raw.get("published_at") or item.get("published_at") or article["published_at"])
            articles[index] = article
            updated = True
            break
    if not updated:
        articles.append(article)
    save_articles(site_id, articles)
    return article


def delete_article(site_id: str, slug: str) -> bool:
    articles = load_articles(site_id)
    remaining = [item for item in articles if item.get("slug") != slug]
    if len(remaining) == len(articles):
        return False
    save_articles(site_id, remaining)
    return True


def public_url_for(site_id: str) -> str:
    site = get_site(site_id)
    return f"/{site_id}/"
