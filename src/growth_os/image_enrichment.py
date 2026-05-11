from __future__ import annotations

import html
import hashlib
import json
import mimetypes
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .config import get_site, project_path
from .content_store import load_articles, now_iso, save_articles, slugify
from .sitegen import generate as generate_site

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - Linux installer provides Pillow, fallback stays safe.
    Image = None
    ImageDraw = None
    ImageFont = None

USER_AGENT = "Mozilla/5.0 (compatible; TurkiyeGundemiImageBot/1.0; +https://turkiyegundemi.com)"
REQUEST_TIMEOUT = 7
MAX_IMAGE_BYTES = 8_000_000
PLACEHOLDER_IMAGES = {
    "/assets/images/ankara.png",
    "/assets/images/ekonomi.png",
    "/assets/images/teknoloji.png",
    "/assets/images/son-dakika.png",
    "/assets/images/dunya.png",
    "/assets/images/spor.png",
    "/assets/images/kultur.png",
}
CONTENT_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
GENERATED_IMAGE_PREFIX = "/assets/images/generated/"
TURKISH_STOPWORDS = {
    "acaba",
    "ancak",
    "ardindan",
    "başkanı",
    "başkan",
    "bile",
    "bir",
    "büyük",
    "daha",
    "dair",
    "değil",
    "den",
    "daki",
    "diye",
    "eden",
    "etti",
    "gibi",
    "göre",
    "haber",
    "icin",
    "için",
    "ile",
    "olan",
    "olarak",
    "oldu",
    "olduğunu",
    "son",
    "sonra",
    "şekilde",
    "var",
    "ve",
    "veya",
    "yeni",
}
VISUAL_PROFILES = {
    "siyaset": ("meclis", "bakan", "parti", "cumhurbaşkanı", "cumhurbaskani", "seçim", "secim", "belediye", "başkan", "baskan", "özel", "ozel", "erdoğan", "erdogan"),
    "toplum": ("kadın", "kadin", "çocuk", "cocuk", "öğrenci", "ogrenci", "işçi", "isci", "emekli", "protesto", "toplum", "sosyal"),
    "hukuk": ("dava", "mahkeme", "savcı", "savci", "soruşturma", "sorusturma", "tutuklama", "gözaltı", "gozalti", "iddianame"),
    "afet": ("deprem", "yangın", "yangin", "sel", "fırtına", "firtina", "kaza", "yaralı", "yarali", "can kaybı", "can kaybi"),
    "ekonomi": ("piyasa", "borsa", "dolar", "euro", "faiz", "enflasyon", "ticaret", "yatırım", "yatirim", "şirket", "sirket"),
    "dunya": ("abd", "avrupa", "iran", "rusya", "ukrayna", "savaş", "savas", "ateşkes", "ateskes", "israil", "filistin"),
    "spor": ("futbol", "fenerbahçe", "fenerbahce", "galatasaray", "beşiktaş", "besiktas", "maç", "mac", "transfer"),
    "teknoloji": ("yapay zeka", "teknoloji", "uydu", "siber", "robot", "veri", "telefon", "internet"),
    "medya": ("youtuber", "youtube", "ünlü", "unlu", "sanatçı", "sanatci", "oyuncu", "dizi", "film", "medya", "magazin"),
}


def category_palette(category: str) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    palettes = {
        "son-dakika": ((193, 28, 46), (42, 58, 91), (245, 179, 1)),
        "gundem": ((28, 54, 91), (180, 38, 58), (245, 246, 248)),
        "ekonomi": ((18, 109, 96), (40, 151, 131), (245, 179, 1)),
        "dunya": ((22, 76, 135), (55, 122, 192), (229, 239, 255)),
        "teknoloji": ((68, 78, 186), (106, 102, 214), (238, 242, 255)),
        "spor": ((20, 132, 115), (28, 165, 105), (232, 247, 244)),
        "kultur": ((139, 63, 174), (190, 86, 166), (246, 235, 252)),
        "dosya": ((113, 44, 76), (168, 74, 118), (255, 241, 248)),
    }
    return palettes.get(str(category or "gundem"), palettes["gundem"])


def article_visual_profile(article: dict[str, Any]) -> str:
    category = str(article.get("category") or "").strip()
    text = clean_text(
        " ".join(
            [
                str(article.get("title") or ""),
                str(article.get("summary") or ""),
                " ".join(str(tag) for tag in article.get("tags", []) if tag),
            ]
        )
    ).casefold()
    for profile, keywords in VISUAL_PROFILES.items():
        if any(keyword in text for keyword in keywords):
            return profile
    if category in {"ekonomi", "dunya", "spor", "teknoloji"}:
        return category
    return "toplum"


def default_image_for_category(category: str) -> str:
    mapping = {
        "son-dakika": "/assets/images/son-dakika.png",
        "gundem": "/assets/images/ankara.png",
        "ekonomi": "/assets/images/ekonomi.png",
        "dunya": "/assets/images/dunya.png",
        "teknoloji": "/assets/images/teknoloji.png",
        "spor": "/assets/images/spor.png",
        "kultur": "/assets/images/kultur.png",
        "dosya": "/assets/images/dosya.png",
    }
    return mapping.get(str(category or "").strip(), "/assets/images/ankara.png")


def needs_category_fallback(article: dict[str, Any]) -> bool:
    current = str(article.get("image") or "").strip()
    expected = default_image_for_category(str(article.get("category") or "gundem"))
    return not current or (current in PLACEHOLDER_IMAGES and current != expected)


def apply_category_fallbacks(site_id: str, *, publish_site: bool = False) -> dict[str, Any]:
    articles = load_articles(site_id)
    changed = 0
    updated_articles: list[dict[str, Any]] = []
    for article in articles:
        updated = dict(article)
        if needs_category_fallback(updated):
            updated["image"] = default_image_for_category(str(updated.get("category") or "gundem"))
            updated["image_alt"] = str(updated.get("image_alt") or updated.get("title") or "").strip()
            changed += 1
        updated_articles.append(updated)
    if changed:
        save_articles(site_id, updated_articles)
    public_dir = str(generate_site(site_id)) if publish_site and changed else None
    return {"ok": True, "changed": changed, "total": len(updated_articles), "public_dir": public_dir}


def generated_image_path(site_id: str, article: dict[str, Any]) -> Path:
    site = get_site(site_id)
    public_dir = project_path(site["public_dir"])
    title = str(article.get("title") or article.get("slug") or "haber")
    category = str(article.get("category") or "gundem")
    source = str(article.get("source_url") or article.get("automation_signature") or "")
    digest = hashlib.sha256(f"{title}|{category}|{source}".encode("utf-8", errors="ignore")).hexdigest()[:10]
    filename = f"{slugify(title)[:80]}-{digest}.png"
    return public_dir / "assets" / "images" / "generated" / filename


def generated_image_url(site_id: str, article: dict[str, Any]) -> str:
    return f"{GENERATED_IMAGE_PREFIX}{generated_image_path(site_id, article).name}"


def image_file_exists(site_id: str, image_url: str) -> bool:
    if not image_url.startswith("/"):
        return False
    site = get_site(site_id)
    return (project_path(site["public_dir"]) / image_url.lstrip("/")).exists()


def needs_related_visual(site_id: str, article: dict[str, Any], *, force: bool = False) -> bool:
    current = str(article.get("image") or "").strip()
    if force:
        return True
    if not current or current in PLACEHOLDER_IMAGES:
        return True
    if current.startswith(GENERATED_IMAGE_PREFIX) and not image_file_exists(site_id, current):
        return True
    return False


def load_font(size: int, *, bold: bool = False) -> Any:
    if ImageFont is None:
        return None
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
    ]
    for candidate in candidates:
        try:
            path = Path(candidate)
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def text_width(draw: Any, text: str, font: Any) -> int:
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return int(right - left)


def wrap_text(draw: Any, text: str, font: Any, max_width: int, max_lines: int) -> list[str]:
    words = clean_text(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and text_width(draw, candidate, font) > max_width:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
        else:
            current = candidate
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len(" ".join(words)) > len(" ".join(lines)):
        lines[-1] = lines[-1].rstrip(" .,:;") + "..."
    return lines


def article_keywords(article: dict[str, Any], limit: int = 5) -> list[str]:
    text = clean_text(
        " ".join(
            [
                str(article.get("title") or ""),
                str(article.get("summary") or ""),
                " ".join(str(tag) for tag in article.get("tags", []) if tag),
            ]
        )
    )
    words = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]{4,}", text)
    seen: set[str] = set()
    keywords: list[str] = []
    for word in words:
        key = slugify(word)
        if not key or key in seen or key in TURKISH_STOPWORDS:
            continue
        seen.add(key)
        keywords.append(word[:22])
        if len(keywords) >= limit:
            break
    return keywords


def blend(first: tuple[int, int, int], second: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    return tuple(int(first[index] * (1 - ratio) + second[index] * ratio) for index in range(3))


def draw_background(draw: Any, width: int, height: int, primary: tuple[int, int, int], secondary: tuple[int, int, int]) -> None:
    top = blend(primary, (255, 255, 255), 0.08)
    bottom = blend(secondary, (255, 255, 255), 0.12)
    for y in range(height):
        ratio = y / max(1, height - 1)
        draw.line([(0, y), (width, y)], fill=blend(top, bottom, ratio))
    for offset in range(-260, width, 230):
        draw.polygon(
            [(offset, height + 60), (offset + 150, height + 60), (offset + 560, -40), (offset + 410, -40)],
            fill=(*blend(primary, secondary, 0.45), 95),
        )
    draw.rectangle((0, int(height * 0.68), width, height), fill=(4, 17, 35, 44))
    for index, size in enumerate((420, 330, 260)):
        x = width - 180 - index * 210
        y = 70 + index * 95
        draw.ellipse((x - size // 2, y - size // 2, x + size // 2, y + size // 2), outline=(255, 255, 255, 45), width=9)
    draw.rounded_rectangle((34, 34, width - 34, height - 34), radius=28, outline=(255, 255, 255, 58), width=2)


def draw_motif(draw: Any, category: str, width: int, height: int, accent: tuple[int, int, int], profile: str) -> None:
    soft = (*accent, 170)
    if profile == "siyaset":
        base_y = 555
        draw.rectangle((650, base_y, 1130, base_y + 36), fill=(255, 255, 255, 105))
        for x in range(690, 1091, 70):
            draw.rectangle((x, 350, x + 34, base_y), fill=(255, 255, 255, 88))
            draw.polygon((x - 14, 350, x + 17, 315, x + 48, 350), fill=(255, 255, 255, 120))
        draw.polygon((630, 330, 890, 230, 1150, 330), outline=soft, fill=(255, 255, 255, 42))
    elif profile == "toplum":
        for index, x in enumerate(range(680, 1130, 70)):
            y = 330 + (index % 4) * 28
            draw.ellipse((x, y, x + 42, y + 42), fill=(255, 255, 255, 112))
            draw.rounded_rectangle((x - 10, y + 48, x + 52, y + 145), radius=26, fill=(255, 255, 255, 70))
        draw.line((640, 575, 1140, 575), fill=soft, width=7)
    elif profile == "medya":
        draw.rounded_rectangle((700, 245, 1120, 555), radius=24, fill=(255, 255, 255, 70), outline=soft, width=7)
        draw.polygon((875, 335, 875, 470, 1015, 402), fill=(255, 255, 255, 150))
        for x, y in ((690, 210), (1030, 205), (760, 585), (1110, 585)):
            draw.rounded_rectangle((x, y, x + 70, y + 46), radius=10, fill=(255, 255, 255, 90))
    elif profile == "hukuk":
        draw.polygon((710, 520, 1060, 520, 1010, 570, 760, 570), fill=(255, 255, 255, 90))
        draw.rectangle((850, 250, 920, 520), fill=(255, 255, 255, 105))
        draw.line((715, 305, 1055, 305), fill=soft, width=8)
        draw.polygon((710, 305, 880, 230, 1050, 305), fill=(255, 255, 255, 74))
        for x in (760, 990):
            draw.line((x, 305, x, 470), fill=soft, width=5)
            draw.line((x - 66, 390, x + 66, 390), fill=soft, width=5)
            draw.arc((x - 66, 350, x + 66, 500), 0, 180, fill=soft, width=6)
    elif profile == "afet":
        draw.polygon((710, 560, 820, 330, 900, 560), fill=(255, 255, 255, 90))
        draw.polygon((870, 560, 1030, 250, 1140, 560), fill=(255, 255, 255, 70))
        draw.line((690, 480, 1160, 420), fill=soft, width=8)
        draw.line((730, 425, 780, 370, 835, 430, 890, 360, 980, 455), fill=(255, 255, 255, 155), width=8)
    elif profile == "ekonomi" or category == "ekonomi":
        points = [(680, 520), (790, 455), (900, 485), (1010, 350), (1130, 280)]
        draw.line(points, fill=soft, width=8)
        for point in points:
            draw.ellipse((point[0] - 12, point[1] - 12, point[0] + 12, point[1] + 12), fill=accent)
        for x, h in ((710, 120), (790, 190), (870, 150), (950, 260), (1030, 310)):
            draw.rounded_rectangle((x, 590 - h, x + 42, 590), radius=8, fill=(255, 255, 255, 78))
    elif profile == "spor" or category == "spor":
        draw.rectangle((720, 220, 1120, 560), outline=soft, width=7)
        draw.ellipse((835, 270, 1005, 440), outline=soft, width=7)
        draw.line((920, 220, 920, 560), fill=soft, width=5)
    elif profile == "teknoloji" or category == "teknoloji":
        nodes = [(760, 250), (920, 210), (1060, 310), (980, 470), (790, 430)]
        for start, end in zip(nodes, nodes[1:] + nodes[:1]):
            draw.line((start, end), fill=soft, width=5)
        for x, y in nodes:
            draw.rounded_rectangle((x - 22, y - 22, x + 22, y + 22), radius=8, fill=accent)
    elif profile == "dunya" or category == "dunya":
        draw.ellipse((760, 180, 1120, 540), outline=soft, width=8)
        draw.arc((820, 180, 1060, 540), 80, 280, fill=soft, width=5)
        draw.arc((820, 180, 1060, 540), -100, 100, fill=soft, width=5)
        draw.line((760, 360, 1120, 360), fill=soft, width=5)
    elif category == "kultur":
        draw.rectangle((760, 240, 1100, 520), outline=soft, width=7)
        draw.line((815, 240, 815, 520), fill=soft, width=5)
        draw.line((900, 240, 900, 520), fill=soft, width=5)
        draw.line((985, 240, 985, 520), fill=soft, width=5)
    elif category == "dosya":
        draw.rounded_rectangle((720, 225, 1080, 560), radius=20, fill=(255, 255, 255, 62), outline=soft, width=7)
        for index, y in enumerate((285, 355, 425, 495)):
            draw.line((780, y, 1035, y), fill=soft, width=6)
            draw.ellipse((745, y - 10, 765, y + 10), fill=accent)
        draw.rectangle((1080, 255, 1130, 590), fill=(255, 255, 255, 75))
    else:
        draw.arc((780, 220, 1080, 520), 200, 520, fill=soft, width=9)
        draw.line((760, 480, 1120, 300), fill=soft, width=6)
        draw.ellipse((1010, 250, 1080, 320), fill=accent)


def generate_related_visual(site_id: str, article: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    if Image is None or ImageDraw is None:
        updated = dict(article)
        updated["image"] = default_image_for_category(str(updated.get("category") or "gundem"))
        return {"ok": False, "updated": True, "article": updated, "reason": "Pillow bulunamadi; kategori gorseli atandi"}
    if not needs_related_visual(site_id, article, force=force):
        return {"ok": True, "updated": False, "article": dict(article), "reason": "haber gorseli zaten var"}

    updated = dict(article)
    category = str(updated.get("category") or "gundem")
    profile = article_visual_profile(updated)
    primary, secondary, accent = category_palette(category)
    width, height = 1200, 760
    image = Image.new("RGB", (width, height), primary)
    draw = ImageDraw.Draw(image, "RGBA")
    draw_background(draw, width, height, primary, secondary)
    draw_motif(draw, category, width, height, accent, profile)

    category_font = load_font(28, bold=True)
    small_font = load_font(24, bold=False)
    brand_font = load_font(26, bold=True)

    draw.rounded_rectangle((52, 48, 210, 108), radius=14, fill=(255, 255, 255, 230))
    draw.rounded_rectangle((68, 60, 118, 96), radius=8, fill=(195, 25, 45, 255))
    draw.text((79, 64), "TG", font=brand_font, fill=(255, 255, 255, 255))
    draw.text((130, 63), "HABER", font=small_font, fill=primary)
    category_label = str(updated.get("category") or "gundem").replace("-", " ").upper()
    draw.rounded_rectangle((52, 132, 52 + max(190, text_width(draw, category_label, category_font) + 36), 184), radius=8, fill=(255, 255, 255, 235))
    draw.text((70, 142), category_label, font=category_font, fill=primary)

    title = clean_text(str(updated.get("title") or "Türkiye Gündemi"))
    keywords = article_keywords(updated)
    # Keep generated visuals text-light. The page template already renders the headline on top of cards.
    draw.rounded_rectangle((52, 604, 525, 656), radius=18, fill=(255, 255, 255, 160))
    draw.text((78, 618), "TÜRKİYE GÜNDEMİ", font=small_font, fill=primary)
    for index, keyword in enumerate(keywords[:3]):
        x = 78 + index * 155
        draw.rounded_rectangle((x, 674, x + 130, 716), radius=18, fill=(255, 255, 255, 185))
        draw.text((x + 16, 684), keyword[:16], font=small_font, fill=primary)

    source = clean_text(str(updated.get("source_name") or "Türkiye Gündemi Haber Merkezi"))
    draw.rounded_rectangle((665, 662, 1120, 716), radius=18, fill=(255, 255, 255, 160))
    draw.text((690, 676), source[:34], font=small_font, fill=primary)
    draw.text((935, 676), "turkiyegundemi.com", font=small_font, fill=(255, 255, 255, 220))

    target = generated_image_path(site_id, updated)
    target.parent.mkdir(parents=True, exist_ok=True)
    if force or not target.exists():
        image.save(target, format="PNG", optimize=True)
    updated["image"] = f"{GENERATED_IMAGE_PREFIX}{target.name}"
    updated["image_alt"] = f"{title} haberi için Türkiye Gündemi görseli"
    updated["image_provider"] = "generated-related"
    updated["image_prompt"] = f"{profile}: " + ", ".join(keywords)
    updated["image_enriched_at"] = now_iso()
    return {"ok": True, "updated": True, "article": updated, "reason": "haberle iliskili yerel gorsel uretildi"}


def apply_related_visuals(
    site_id: str,
    *,
    force: bool = False,
    only_missing: bool = True,
    publish_site: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    articles = load_articles(site_id)
    changed = 0
    scanned = 0
    results: list[dict[str, Any]] = []
    max_items = int(limit) if limit is not None else None
    for index, article in enumerate(articles):
        if max_items is not None and scanned >= max_items:
            break
        if only_missing and not needs_related_visual(site_id, article, force=force):
            continue
        scanned += 1
        outcome = generate_related_visual(site_id, article, force=force)
        articles[index] = outcome["article"]
        if outcome.get("updated"):
            changed += 1
        results.append(
            {
                "slug": article.get("slug", ""),
                "title": article.get("title", ""),
                "updated": bool(outcome.get("updated")),
                "reason": str(outcome.get("reason", "")),
                "image": outcome["article"].get("image", ""),
            }
        )
    if changed:
        save_articles(site_id, articles)
    public_dir = str(generate_site(site_id)) if publish_site and changed else None
    return {"ok": True, "site_id": site_id, "scanned_count": scanned, "updated_count": changed, "results": results, "public_dir": public_dir}


class ImageCandidateParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.meta_alt = ""
        self.candidates: list[dict[str, Any]] = []

    def add_candidate(self, url: str, *, score: int, alt: str = "", source: str = "page") -> None:
        normalized = normalize_url(url, self.base_url)
        if not normalized or is_bad_image_url(normalized):
            return
        self.candidates.append(
            {
                "url": normalized,
                "score": score,
                "alt": clean_text(alt),
                "source": source,
            }
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {str(key).lower(): (value or "") for key, value in attrs}
        if tag == "meta":
            key = (data.get("property") or data.get("name") or data.get("itemprop") or "").strip().lower()
            content = data.get("content", "")
            if key in {"og:image", "og:image:url", "twitter:image", "twitter:image:src", "image", "thumbnailurl"}:
                self.add_candidate(content, score=160, alt=self.meta_alt, source=f"meta:{key}")
            elif key in {"og:image:alt", "twitter:image:alt"}:
                self.meta_alt = clean_text(content)
            return
        if tag == "link":
            rel = data.get("rel", "").lower()
            href = data.get("href", "")
            if "image_src" in rel or ("preload" in rel and data.get("as", "").lower() == "image"):
                self.add_candidate(href, score=115, source=f"link:{rel}")
            return
        if tag != "img":
            return
        source = data.get("src") or data.get("data-src") or data.get("data-original") or data.get("data-lazy-src")
        if not source:
            return
        classes = " ".join([data.get("class", ""), data.get("id", "")]).lower()
        score = 50
        if any(token in classes for token in ("article", "content", "main", "hero", "lead", "featured", "news", "story", "post")):
            score += 35
        if any(token in classes for token in ("logo", "icon", "sprite", "avatar", "banner", "ads", "advert", "footer", "header")):
            score -= 55
        width = parse_int(data.get("width"))
        height = parse_int(data.get("height"))
        if width >= 400 or height >= 300:
            score += 15
        alt = data.get("alt", "")
        if alt:
            score += 5
        self.add_candidate(source, score=score, alt=alt, source="img")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or "")).strip())


def parse_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def normalize_url(url: str, base_url: str) -> str:
    value = clean_text(url)
    if not value:
        return ""
    if value.startswith("//"):
        parsed_base = urllib.parse.urlparse(base_url)
        return f"{parsed_base.scheme or 'https'}:{value}"
    normalized = urllib.parse.urljoin(base_url, value)
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return urllib.parse.urlunparse(parsed._replace(fragment=""))


def is_bad_image_url(url: str) -> bool:
    lowered = url.casefold()
    blocked = [
        "logo",
        "icon",
        "sprite",
        "avatar",
        "favicon",
        "blank.",
        "placeholder",
        "analytics",
        "pixel",
        "doubleclick",
        "/ads/",
        "advert",
        "reklam",
    ]
    return any(token in lowered for token in blocked)


def fetch_text(url: str) -> tuple[str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        payload = response.read(1_000_000)
        content_type = response.headers.get("content-type", "")
        final_url = response.geturl()
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    try:
        page = payload.decode(charset, errors="replace")
    except LookupError:
        page = payload.decode("utf-8", errors="replace")
    return page, final_url


def extract_jsonld_candidates(page: str, base_url: str) -> list[dict[str, Any]]:
    matches = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page,
        re.I | re.S,
    )
    candidates: list[dict[str, Any]] = []
    for raw in matches:
        text = html.unescape(raw).strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except Exception:
            continue
        for image_url in find_jsonld_images(data):
            normalized = normalize_url(image_url, base_url)
            if normalized and not is_bad_image_url(normalized):
                candidates.append({"url": normalized, "score": 145, "alt": "", "source": "jsonld"})
    return candidates


def find_jsonld_images(value: Any) -> list[str]:
    results: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in {"image", "thumbnailurl", "contenturl", "url"}:
                if isinstance(nested, str):
                    results.append(nested)
                elif isinstance(nested, dict):
                    for candidate_key in ("url", "contentUrl"):
                        if nested.get(candidate_key):
                            results.append(str(nested[candidate_key]))
                elif isinstance(nested, list):
                    for item in nested:
                        if isinstance(item, str):
                            results.append(item)
                        elif isinstance(item, dict) and item.get("url"):
                            results.append(str(item["url"]))
            else:
                results.extend(find_jsonld_images(nested))
    elif isinstance(value, list):
        for item in value:
            results.extend(find_jsonld_images(item))
    return results


def discover_image_candidates(article_url: str) -> list[dict[str, Any]]:
    page, final_url = fetch_text(article_url)
    parser = ImageCandidateParser(final_url)
    try:
        parser.feed(page)
    except Exception:
        pass
    candidates = parser.candidates + extract_jsonld_candidates(page, final_url)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in sorted(candidates, key=lambda item: int(item.get("score", 0)), reverse=True):
        url = candidate.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(candidate)
    return unique[:5]


def detect_extension(content_type: str, url: str, payload: bytes) -> str:
    media = content_type.split(";", 1)[0].strip().lower()
    if media in CONTENT_EXTENSIONS:
        return CONTENT_EXTENSIONS[media]
    path = urllib.parse.urlparse(url).path
    guessed = Path(path).suffix.lower()
    if guessed in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if guessed == ".jpeg" else guessed
    if payload.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return ".webp"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    return ".jpg"


def download_image(site_id: str, slug: str, image_url: str, *, referer: str = "") -> str:
    site = get_site(site_id)
    public_dir = project_path(site["public_dir"])
    target_dir = public_dir / "assets" / "images" / "news"
    target_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT, "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(image_url, headers=headers)
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        payload = response.read(MAX_IMAGE_BYTES + 1)
        content_type = response.headers.get("content-type", "")
    if len(payload) > MAX_IMAGE_BYTES:
        raise ValueError("Gorsel dosyasi izin verilen boyutu asiyor")
    media = content_type.split(";", 1)[0].strip().lower()
    if media and not media.startswith("image/"):
        raise ValueError("Kaynak gorsel degil")
    extension = detect_extension(content_type, image_url, payload)
    filename = f"{slug}{extension}"
    target = target_dir / filename
    target.write_bytes(payload)
    return f"/assets/images/news/{filename}"


def image_needs_enrichment(article: dict[str, Any], *, force: bool = False) -> bool:
    image = str(article.get("image") or "").strip()
    if force:
        return True
    if not image:
        return True
    if image.startswith("http://") or image.startswith("https://"):
        return True
    return image in PLACEHOLDER_IMAGES


def enrich_article_image(site_id: str, article: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    updated = dict(article)
    if not image_needs_enrichment(updated, force=force):
        return {"ok": True, "updated": False, "article": updated, "reason": "zaten uygun gorsel var"}

    candidate_urls: list[tuple[str, str, str]] = []
    current = str(updated.get("image") or "").strip()
    if current.startswith(("http://", "https://")):
        candidate_urls.append((current, str(updated.get("image_alt") or updated.get("title") or ""), "existing-remote"))

    source_url = str(updated.get("source_url") or "").strip()
    last_error = ""
    if source_url.startswith(("http://", "https://")):
        try:
            discovered = discover_image_candidates(source_url)
        except Exception as exc:
            discovered = []
            last_error = str(exc)
        for candidate in discovered:
            candidate_urls.append((str(candidate.get("url", "")), str(candidate.get("alt", "")), str(candidate.get("source", "page"))))

    seen: set[str] = set()
    for url, alt, provider in candidate_urls:
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            local_path = download_image(site_id, str(updated.get("slug") or "haber"), url, referer=source_url)
        except Exception as exc:
            last_error = str(exc)
            continue
        updated["image"] = local_path
        updated["image_alt"] = clean_text(alt or updated.get("title") or updated.get("summary") or "")
        updated["image_source_url"] = url
        updated["image_provider"] = provider
        updated["image_enriched_at"] = now_iso()
        return {"ok": True, "updated": True, "article": updated, "reason": "gorsel indirildi"}

    fallback = default_image_for_category(str(updated.get("category") or ""))
    if not str(updated.get("image") or "").strip():
        updated["image"] = fallback
        updated["image_alt"] = clean_text(updated.get("title") or updated.get("summary") or "")
        return {"ok": True, "updated": True, "article": updated, "reason": "kategori varsayilan gorseli atandi"}
    return {
        "ok": False,
        "updated": False,
        "article": updated,
        "reason": last_error or "uygun gorsel bulunamadi",
    }


def enrich_existing_articles(
    site_id: str = "turkiye-gundemi",
    *,
    force: bool = False,
    only_missing: bool = True,
    publish_site: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    articles = load_articles(site_id)
    changed = 0
    scanned = 0
    results: list[dict[str, Any]] = []
    max_items = int(limit) if limit is not None else None
    for index, article in enumerate(articles):
        if max_items is not None and scanned >= max_items:
            break
        if only_missing and not image_needs_enrichment(article, force=force):
            continue
        scanned += 1
        outcome = enrich_article_image(site_id, article, force=force)
        articles[index] = outcome["article"]
        if outcome.get("updated"):
            changed += 1
        results.append(
            {
                "slug": article.get("slug", ""),
                "title": article.get("title", ""),
                "updated": bool(outcome.get("updated")),
                "reason": str(outcome.get("reason", "")),
                "image": outcome["article"].get("image", ""),
            }
        )
    if changed:
        save_articles(site_id, articles)
    public_dir = str(generate_site(site_id)) if publish_site and changed else None
    return {
        "ok": True,
        "site_id": site_id,
        "scanned_count": scanned,
        "updated_count": changed,
        "results": results,
        "public_dir": public_dir,
    }
