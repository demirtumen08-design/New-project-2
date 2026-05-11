"""Editorial quality checks shared by the admin panel and static generator."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import unicodedata
from typing import Any

from .content_store import load_articles, now_iso, save_articles


ROBOTIC_PATTERNS = (
    "yeni bilgi geldikce",
    "haber metni guncellenerek",
    "zaman cizelgesi",
    "ilgili kurum aciklamalari",
    "haber akisinda ayrica takip",
    "metin guncel bilgilerle genisletilecek",
    "gelisme hakkinda yeni ayrintilar",
    "ayrintilar geldikce aktarilacak",
    "bu gelismede yeni ayrintilar geldikce",
    "gundem gundemindeki",
    "dosyasinda dikkat ceken gelisme",
    "haberleri dosyasinda dikkat ceken",
)

GENERIC_SUMMARY_PATTERNS = (
    "gelismeye iliskin yeni bilgiler paylasildi",
    "ayrintilar netlesiyor",
    "son dakika gelismesi",
    "kamuoyunun gundemine geldi",
    "detaylar haberimizde",
    "guncel bilgilerle takip ediliyor",
)

TITLE_FRAGMENT_PATTERNS = (
    "basligi gundemde",
    "sorusu gundemde",
    "dosyasinda dikkat ceken gelisme",
    "haberleri dosyasinda",
    "onceden isitilmis",
    "derece firinda",
    "dakika pisirin",
    "sicak servis",
    "malzemeleri",
    "tarifi icin",
    "saat 08",
    "saat 09",
    "saat 10",
    "siralarinda",
    "mahallesinde yasandi",
    "olay yerine",
    "ekipleri sevk edildi",
    "sube mudurlugu ekiplerinin",
    "dolayisiyla tbmm",
    "bagli acil",
    "sorusuna yanit araniyor",
    "kamuoyunda yer alan haberlere gore",
    "kulislerde yer alan iddialara gore",
)

TITLE_ENDING_FRAGMENTS = (
    " da",
    " de",
    " ve",
    " ile",
    " icin",
    " nedeniyle",
    " ekiplerinin",
    " tbmm",
    " acil",
    " temaslarda",
    " hesap",
    " soru",
    " cevap",
    " yanit",
    " sözleri",
    " sozleri",
)

MOJIBAKE_TOKENS = ("�", "Ã", "Ä", "Å", "â€", "ð", "þ")
MALFORMED_TEXT_PATTERNS = (
    r",\s*\.",
    r"\bDevamında\b",
    r"\b(kaydederek|belirterek|aktararak|bildirerek|vurgulayarak|eleştirerek|dile getirerek|ifade ederek),?\s*\.",
)
TITLE_COMPLETE_SIGNAL_RE = re.compile(
    r"\b(açıkladı|duyurdu|belirlendi|netleşti|başladı|tamamlandı|görüştü|yükseldi|düştü|çıktı|geldi|yaşandı|"
    r"gündemde|istedi|hazırlandı|düzenlendi|yapıldı|başvurdu|açıldı|kapatıldı|sunuldu|verildi|aldı|ulaştı|"
    r"vurguladı|söyledi|dile getirdi|kayda geçti|öne çıktı|girdi|kutladı|yalanladı|yalanlama|almayın|"
    r"kaçının|uyardı|çağırdı|karar|uyarı|"
    r"rapor|operasyon|soruşturma|dava|övgü)\b",
    re.I,
)
BLOCKING_FLAGS = {
    "robotic_template",
    "generic_summary",
    "future_date",
    "encoding_damage",
    "title_fragment",
    "malformed_sentence",
}
TITLE_REPAIR_REMOVALS = (
    "basligi gundemde",
    "sorusu gundemde",
    "dosyasinda dikkat ceken gelisme",
    "haberleri dosyasinda dikkat ceken gelisme",
)


def _fold(value: Any) -> str:
    text = str(value or "").casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"}))
    text = text.replace("'", "").replace("’", "")
    text = re.sub(r"[_\-–—:;,.!?()\[\]\"“”]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _text_parts(article: dict[str, Any]) -> list[str]:
    parts = [
        str(article.get("title") or ""),
        str(article.get("summary") or ""),
        str(article.get("spot") or ""),
    ]
    body = article.get("body")
    if isinstance(body, list):
        parts.extend(str(item or "") for item in body)
    else:
        parts.append(str(body or ""))
    return [part for part in parts if part.strip()]


def _body_paragraphs(article: dict[str, Any]) -> list[str]:
    body = article.get("body")
    if isinstance(body, list):
        return [str(item).strip() for item in body if str(item).strip()]
    if isinstance(body, str) and body.strip():
        return [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    return []


def _word_count(value: str) -> int:
    return len(re.findall(r"\w+", value, flags=re.UNICODE))


def _has_pattern(value: str, patterns: tuple[str, ...]) -> bool:
    folded = _fold(value)
    return any(pattern in folded for pattern in patterns)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_future_article(article: dict[str, Any]) -> bool:
    published_at = _parse_datetime(article.get("published_at") or article.get("created_at"))
    if not published_at:
        return False
    return published_at > datetime.now(timezone.utc) + timedelta(minutes=10)


def article_quality_flags(article: dict[str, Any]) -> list[str]:
    """Return stable machine-readable warnings for one content item."""

    category = str(article.get("category") or "").casefold()
    is_dossier = category == "dosya"
    parts = _text_parts(article)
    combined = " ".join(parts)
    title = str(article.get("title") or "")
    body = _body_paragraphs(article)
    body_text = " ".join(body)
    flags: list[str] = []

    if _has_pattern(combined, ROBOTIC_PATTERNS):
        flags.append("robotic_template")
    if not is_dossier and _has_pattern(title, TITLE_FRAGMENT_PATTERNS):
        flags.append("title_fragment")
    folded_title = _fold(title)
    if not is_dossier and _word_count(title) > 8 and folded_title.endswith(TITLE_ENDING_FRAGMENTS):
        flags.append("title_fragment")
    if not is_dossier and 2 < _word_count(title) <= 5 and not TITLE_COMPLETE_SIGNAL_RE.search(title):
        flags.append("title_fragment")
    if not is_dossier and ('"' in title and title.count('"') % 2 == 1):
        flags.append("title_fragment")
    if not is_dossier and ("“" in title and title.count("“") != title.count("”")):
        flags.append("title_fragment")
    if not is_dossier and re.search(r"[!?]:\s+[a-zçğıöşü]", title):
        flags.append("title_fragment")
    if not is_dossier and re.search(r":\s*['‘“][^'’”]+$", title):
        flags.append("title_fragment")
    if not is_dossier and _colon_tail_is_fragment(title):
        flags.append("title_fragment")
    if not is_dossier and title.count(":") >= 2 and _word_count(title) > 9:
        flags.append("title_fragment")
    if not is_dossier and _word_count(title) > 26 and _has_pattern(title, (" dedi", " belirtildi", " aciklandi", " aktarildi")):
        flags.append("title_fragment")
    if not is_dossier and _has_pattern(str(article.get("summary") or ""), GENERIC_SUMMARY_PATTERNS):
        flags.append("generic_summary")
    if not is_dossier and any(re.search(pattern, combined, flags=re.I) for pattern in MALFORMED_TEXT_PATTERNS):
        flags.append("malformed_sentence")
    if _is_future_article(article):
        flags.append("future_date")
    if any(token in combined for token in MOJIBAKE_TOKENS):
        flags.append("encoding_damage")
    if not is_dossier and _word_count(body_text) < 90:
        flags.append("thin_body")
    if not is_dossier and len(body) < 2:
        flags.append("too_few_paragraphs")
    if not is_dossier and not str(article.get("source_url") or "").strip():
        flags.append("missing_source_url")

    return flags


def title_is_fragment(value: str) -> bool:
    probe = {"title": value, "summary": "", "body": ["Geçici kontrol metni."], "category": "gundem"}
    flags = article_quality_flags(probe)
    return "title_fragment" in flags or "encoding_damage" in flags


def _colon_tail_is_fragment(title: str) -> bool:
    if ":" not in title:
        return False
    _lead, tail = title.split(":", 1)
    tail = tail.strip(" .,-;:")
    if not tail:
        return True
    folded_tail = _fold(tail)
    tail_words = _word_count(tail)
    tail_has_news_signal = bool(TITLE_COMPLETE_SIGNAL_RE.search(tail)) or bool(
        re.search(r"\b\d+(?:[,.]\d+)?\s*(?:tl|lira|dolar|euro|milyon|milyar|yil|ay|gun|kisi)\b", folded_tail)
    )
    if tail_words <= 10 and re.search(r"\b\d+$", folded_tail):
        return True
    if folded_tail.endswith(TITLE_ENDING_FRAGMENTS):
        return True
    if tail_words >= 3 and not tail_has_news_signal:
        return True
    if re.search(r"\b(duzenledigi|duzenlenen|yaptigi|katildigi|verdigi|oldugu|ettigi|belirttigi)\b", folded_tail):
        complete_signal = re.search(
            r"\b(geldi|yapildi|tamamlandi|duzenlendi|bulustu|katildi|verildi|edildi|aciklandi|vurgulandi|soyledi|dedi|kaydetti)\b",
            folded_tail,
        )
        if not complete_signal:
            return True
    return False


def repair_title_fragment(title: str, source_title: str = "") -> str:
    """Shorten a broken headline while preserving the subject."""

    candidates: list[str] = []
    for raw in (source_title, title):
        text = str(raw or "").strip()
        if not text:
            continue
        text = re.sub(r"\s+", " ", text).strip(" .,-;")
        if re.search(r"[!?]:", text):
            candidates.append(re.split(r"(?<=[!?]):", text, maxsplit=1)[0].strip(" .,-;"))

        if ":" in text:
            parts = [part.strip(" .,:;") for part in text.split(":") if part.strip(" .,:;")]
            if parts:
                if len(parts) >= 2:
                    tail_folded = _fold(parts[1])
                    tail_word_count = _word_count(parts[1])
                    tail_has_number = bool(re.search(r"\d", parts[1]))
                    tail_looks_complete = bool(
                        re.search(
                            r"\b(var|yok|başladı|basladi|açıklandı|aciklandi|yakalandı|yakalandi|gözaltı|gozalti|tutuklama|yaralı|yarali|ölü|olu)\b",
                            tail_folded,
                        )
                    )
                    if (
                        tail_word_count <= 7
                        and (tail_has_number or tail_looks_complete)
                        and not tail_folded.endswith(TITLE_ENDING_FRAGMENTS)
                    ):
                        candidates.append(f"{parts[0]}: {parts[1]}")
                candidates.append(parts[0])
            if len(parts) == 2:
                tail_folded = _fold(parts[1])
                if (
                    len(parts[1]) <= 72
                    and _word_count(parts[1]) <= 7
                    and bool(re.search(r"\d", parts[1]))
                    and not tail_folded.endswith(TITLE_ENDING_FRAGMENTS)
                    and not any(pattern in tail_folded for pattern in TITLE_REPAIR_REMOVALS)
                ):
                    candidates.append(f"{parts[0]}: {parts[1]}")

        text = re.sub(r"\s+(başlığı|basligi)\s+(gündemde|gundemde)$", "", text, flags=re.I)
        text = re.sub(r"\s+(sorusu)\s+(gündemde|gundemde)$", "", text, flags=re.I)
        text = re.sub(r"\s+dosyasında dikkat çeken gelişme$", "", text, flags=re.I)
        text = re.sub(r"\s+dosyasinda dikkat ceken gelisme$", "", text, flags=re.I)
        candidates.append(text)

        sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip(" .,-;")
        if sentence and sentence != text:
            candidates.append(sentence)

    cleaned_candidates: list[str] = []
    for candidate in candidates:
        candidate = re.sub(r"\s+", " ", candidate).strip(" .,-;:")
        candidate = re.sub(r"\s+(ve|ile|için|icin|nedeniyle|ekiplerinin|temaslarda)$", "", candidate, flags=re.I).strip(" .,-;:")
        if not candidate:
            continue
        if candidate.count('"') % 2 == 1:
            candidate = candidate.replace('"', "").strip(" .,-;:")
        if 18 <= len(candidate) <= 118 and not title_is_fragment(candidate):
            cleaned_candidates.append(candidate)

    if cleaned_candidates:
        return cleaned_candidates[0]
    return str(title or source_title or "").strip()


def publication_blocking_flags(article: dict[str, Any]) -> list[str]:
    flags = article_quality_flags(article)
    blocking = [flag for flag in flags if flag in BLOCKING_FLAGS]

    score = article.get("quality_score")
    try:
        quality_score = float(score)
    except (TypeError, ValueError):
        quality_score = 0.0

    if "thin_body" in flags and quality_score < 75:
        blocking.append("thin_body")
    if "too_few_paragraphs" in flags and quality_score < 75:
        blocking.append("too_few_paragraphs")

    return list(dict.fromkeys(blocking))


def is_publication_safe(article: dict[str, Any]) -> bool:
    if str(article.get("category") or "").casefold() == "dosya":
        return not any(flag in BLOCKING_FLAGS for flag in article_quality_flags(article))
    return not publication_blocking_flags(article)


def audit_articles(articles: list[dict[str, Any]]) -> dict[str, Any]:
    published = [item for item in articles if item.get("status") == "published"]
    drafts = [item for item in articles if item.get("status") == "draft"]
    dossiers = [item for item in articles if str(item.get("category") or "").casefold() == "dosya"]
    risky: list[dict[str, Any]] = []
    issue_count = 0
    blocked_published = 0

    for article in articles:
        flags = article_quality_flags(article)
        blocking = publication_blocking_flags(article)
        if flags:
            issue_count += 1
        if article.get("status") == "published" and blocking:
            blocked_published += 1
        if flags and len(risky) < 80:
            risky.append(
                {
                    "title": article.get("title"),
                    "slug": article.get("slug"),
                    "status": article.get("status"),
                    "category": article.get("category"),
                    "quality_score": article.get("quality_score"),
                    "flags": flags,
                    "blocking_flags": blocking,
                }
            )

    safe_published = [
        item
        for item in published
        if str(item.get("category") or "").casefold() == "dosya" or is_publication_safe(item)
    ]
    return {
        "total": len(articles),
        "published": len(published),
        "drafts": len(drafts),
        "dossiers": len(dossiers),
        "issue_count": issue_count,
        "blocked_published": blocked_published,
        "safe_published": len(safe_published),
        "risky": risky,
    }


def apply_quality_gate(site_id: str, dry_run: bool = False) -> dict[str, Any]:
    articles = load_articles(site_id)
    changed: list[dict[str, Any]] = []
    repaired: list[dict[str, Any]] = []

    for article in articles:
        if article.get("status") != "published":
            continue
        flags = article_quality_flags(article)
        if "title_fragment" in flags:
            repaired_title = repair_title_fragment(
                str(article.get("title") or ""),
                str(article.get("source_title") or article.get("title") or ""),
            )
            if repaired_title and repaired_title != article.get("title"):
                trial = dict(article)
                trial["title"] = repaired_title
                trial_flags = article_quality_flags(trial)
                if "title_fragment" not in trial_flags and not any(flag in BLOCKING_FLAGS for flag in trial_flags):
                    old_title = str(article.get("title") or "")
                    repaired.append(
                        {
                            "title": old_title,
                            "repaired_title": repaired_title,
                            "slug": article.get("slug"),
                        }
                    )
                    if not dry_run:
                        article["title"] = repaired_title
                        article["image_alt"] = f"{repaired_title} haberi için Türkiye Gündemi görseli"
                        article["quality_flags"] = ", ".join(trial_flags)
                        article["modified_at"] = now_iso()
        blocking = publication_blocking_flags(article)
        if not blocking:
            continue
        changed.append(
            {
                "title": article.get("title"),
                "slug": article.get("slug"),
                "flags": blocking,
            }
        )
        if dry_run:
            continue
        article["status"] = "draft"
        article["publish_decision"] = "draft-content-quality-gate"
        article["quality_flags"] = ", ".join(blocking)
        article["modified_at"] = now_iso()

    if changed and not dry_run:
        save_articles(site_id, articles)
    elif repaired and not dry_run:
        save_articles(site_id, articles)

    return {
        "ok": True,
        "dry_run": dry_run,
        "changed_count": len(changed),
        "repaired_count": len(repaired),
        "changed": changed[:100],
        "repaired": repaired[:100],
        "audit": audit_articles(articles),
    }
