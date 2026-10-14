from __future__ import annotations
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Tuple, Optional
from email.utils import parsedate_to_datetime


def parse_twitter_date(date_str: str) -> Tuple[datetime, str, int]:
    """
    Twitter formatındaki tarihi ('Wed Oct 14 12:00:00 +0000 2026')
    UTC datetime, ISO-8601 string ve epoch timestamp olarak döndürür.
    """
    if not date_str:
        now = datetime.now(timezone.utc)
        return now, now.isoformat(), int(now.timestamp())
    
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
    except Exception:
        try:
            # ISO format fallback
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception:
            dt = datetime.now(timezone.utc)

    return dt, dt.isoformat(), int(dt.timestamp())


def extract_media_from_media_list(media_list: List[Dict[str, Any]]) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    """
    Twitter extended_entities / entities içindeki medya listesini tarayarak:
    - Yüksek kaliteli resim URL'leri listesi
    - En yüksek bitrate'li video URL'leri listesi
    - Zengin metadata içeren detaylı medya objeleri listesi döndürür.
    """
    images: List[str] = []
    videos: List[str] = []
    rich_media: List[Dict[str, Any]] = []

    for item in media_list:
        media_type = item.get("type", "")
        media_url_base = item.get("media_url_https", "")

        # Resim (Photo)
        if media_type == "photo" and media_url_base:
            # Orijinal / yüksek kalite URL
            orig_url = f"{media_url_base}?name=orig" if "?" not in media_url_base else media_url_base
            large_url = f"{media_url_base}?name=large" if "?" not in media_url_base else media_url_base
            
            images.append(media_url_base)
            
            sizes = item.get("sizes", {})
            large_size = sizes.get("large", {}) or sizes.get("medium", {})
            width = large_size.get("w")
            height = large_size.get("h")

            rich_media.append({
                "type": "photo",
                "url": media_url_base,
                "orig_url": orig_url,
                "large_url": large_url,
                "width": width,
                "height": height,
                "aspect_ratio": round(width / height, 2) if width and height else None
            })

        # Video veya Animasyonlu GIF
        elif media_type in ["video", "animated_gif"]:
            video_info = item.get("video_info", {})
            variants = video_info.get("variants", [])
            
            # Sadece mp4 formatındaki varyantları filtrele
            mp4_variants = [
                v for v in variants 
                if v.get("content_type") == "video/mp4" and v.get("url")
            ]
            
            best_video_url = None
            best_bitrate = -1
            all_mp4_links = []

            for var in mp4_variants:
                v_url = var.get("url")
                bitrate = var.get("bitrate", 0)
                all_mp4_links.append({"url": v_url, "bitrate": bitrate})
                if bitrate > best_bitrate:
                    best_bitrate = bitrate
                    best_video_url = v_url

            # Eğer bitrate belirtilmemişse ilk mp4'ü al
            if not best_video_url and mp4_variants:
                best_video_url = mp4_variants[0].get("url")

            if best_video_url:
                videos.append(best_video_url)

            # Video kapak görseli
            thumb_url = media_url_base
            duration_ms = video_info.get("duration_millis")
            aspect_ratio_data = video_info.get("aspect_ratio", [16, 9])
            aspect_ratio_str = f"{aspect_ratio_data[0]}:{aspect_ratio_data[1]}" if len(aspect_ratio_data) >= 2 else "16:9"

            rich_media.append({
                "type": media_type,
                "url": best_video_url,
                "thumbnail_url": thumb_url,
                "bitrate": best_bitrate,
                "duration_ms": duration_ms,
                "duration_sec": round(duration_ms / 1000, 1) if duration_ms else None,
                "aspect_ratio": aspect_ratio_str,
                "all_variants": all_mp4_links
            })

    # Tekrar eden linkleri temizle
    images = list(dict.fromkeys(images))
    videos = list(dict.fromkeys(videos))

    return images, videos, rich_media


def extract_card_info(card: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tweet kartındaki (link önizlemesi, haber sitesi kapak görseli vb.) verileri çıkarır.
    """
    card_data = {
        "has_card": False,
        "title": None,
        "description": None,
        "domain": None,
        "url": None,
        "image_url": None
    }

    if not card:
        return card_data

    binding_values = card.get("legacy", {}).get("binding_values", [])
    if isinstance(binding_values, list):
        bv_dict = {}
        for item in binding_values:
            key = item.get("key")
            val = item.get("value", {})
            # Farklı değer tipleri (string_value, image_value, etc.)
            val_content = (
                val.get("string_value") or 
                val.get("image_value", {}).get("url") or 
                val.get("image_large_value", {}).get("url")
            )
            if key and val_content:
                bv_dict[key] = val_content
    elif isinstance(binding_values, dict):
        bv_dict = {
            k: v.get("string_value") or v.get("image_value", {}).get("url")
            for k, v in binding_values.items() if isinstance(v, dict)
        }
    else:
        bv_dict = {}

    if bv_dict:
        card_data["has_card"] = True
        card_data["title"] = bv_dict.get("title") or bv_dict.get("summary_title")
        card_data["description"] = bv_dict.get("description")
        card_data["domain"] = bv_dict.get("vanity_url") or bv_dict.get("domain")
        card_data["url"] = bv_dict.get("card_url") or bv_dict.get("url")
        card_data["image_url"] = (
            bv_dict.get("photo_image_full_size_large") or 
            bv_dict.get("thumbnail_image_large") or 
            bv_dict.get("thumbnail_image_original") or 
            bv_dict.get("summary_photo_image_large") or
            bv_dict.get("player_image_large")
        )

    return card_data


def extract_author_details(tweet: Dict[str, Any]) -> Dict[str, Any]:
    """Kullanıcı ve yazar bilgilerini detaylı olarak ayıklar."""
    user_result = tweet.get("core", {}).get("user_results", {}).get("result", {})
    user_legacy = user_result.get("legacy", {})
    user_core = user_result.get("core", {})

    name = user_legacy.get("name") or user_core.get("name") or ""
    screen_name = user_legacy.get("screen_name") or user_core.get("screen_name") or user_result.get("screen_name", "")
    
    # Yüksek çözünürlüklü profil görseli (_normal yerine _400x400 veya orijinal)
    profile_img = (
        user_legacy.get("profile_image_url_https") or 
        user_result.get("avatar", {}).get("image_url", "")
    )
    profile_img_large = profile_img.replace("_normal.", "_400x400.") if profile_img else ""

    is_verified = (
        user_legacy.get("verified", False) or 
        user_result.get("is_blue_verified", False)
    )

    return {
        "name": name,
        "username": screen_name,
        "screen_name": screen_name,
        "profile_image_url": profile_img,
        "profile_image_url_large": profile_img_large,
        "is_verified": is_verified,
        "followers_count": user_legacy.get("followers_count", 0),
        "author_url": f"https://x.com/{screen_name}" if screen_name else ""
    }


def extract_full_news_data(
    raw_tweet_item: Dict[str, Any], 
    list_config: Any, 
    retention_days: int = 2
) -> Optional[Dict[str, Any]]:
    """
    X API'den yakalanan bir tweet objesinden tüm haber, görsel, video, kart,
    alıntı tweet ve yazar verilerini çıkarır.
    """
    # Tweet nesnesini çöz
    content = raw_tweet_item.get("content", {}).get("itemContent", {}).get("tweet_results", {}).get("result", {})
    if not content:
        return None

    if content.get("__typename") == "TweetWithVisibilityResults":
        tweet = content.get("tweet", {})
    else:
        tweet = content

    tweet_id = tweet.get("rest_id")
    if not tweet_id:
        return None

    legacy = tweet.get("legacy", {})
    full_text = legacy.get("full_text", "")

    # Tarih çözümleme
    created_at_raw = legacy.get("created_at", "")
    created_dt, iso_str, epoch_ts = parse_twitter_date(created_at_raw)
    
    # 2 Günlük TTL hesaplama (Otomatik silinme tarihi)
    expire_dt = created_dt + timedelta(days=retention_days)
    expire_iso = expire_dt.isoformat()
    expire_ts = int(expire_dt.timestamp())

    # Medya Listeleri
    media_list = legacy.get("extended_entities", {}).get("media", [])
    if not media_list:
        media_list = legacy.get("entities", {}).get("media", [])

    images, videos, rich_media = extract_media_from_media_list(media_list)

    # Tweet Kartı (Haber linki önizlemesi)
    card_info = extract_card_info(tweet.get("card", {}))
    # Eğer doğrudan resim yoksa ama haber kartı resmi varsa görsellere ekle
    if not images and card_info.get("image_url"):
        images.append(card_info["image_url"])
        rich_media.append({
            "type": "card_image",
            "url": card_info["image_url"],
            "title": card_info.get("title"),
            "domain": card_info.get("domain")
        })

    # Alıntı Tweet (Quoted Tweet) Medyaları ve Bilgisi
    quoted_data = None
    quoted_result = tweet.get("quoted_status_result", {}).get("result", {})
    if quoted_result:
        q_tweet = quoted_result.get("tweet", {}) if quoted_result.get("__typename") == "TweetWithVisibilityResults" else quoted_result
        q_legacy = q_tweet.get("legacy", {})
        q_media_list = q_legacy.get("extended_entities", {}).get("media", []) or q_legacy.get("entities", {}).get("media", [])
        q_images, q_videos, q_rich_media = extract_media_from_media_list(q_media_list)
        
        # Alıntıdaki medyaları da ana listelere dahil et (böylece hiçbir video/resim kaçmaz)
        for q_img in q_images:
            if q_img not in images:
                images.append(q_img)
        for q_vid in q_videos:
            if q_vid not in videos:
                videos.append(q_vid)

        quoted_author = extract_author_details(q_tweet)
        quoted_data = {
            "tweet_id": q_tweet.get("rest_id"),
            "text": q_legacy.get("full_text", ""),
            "images": q_images,
            "videos": q_videos,
            "author": quoted_author
        }

    # URL ve Hashtag Çözümleme
    entities = legacy.get("entities", {})
    urls_data = entities.get("urls", [])
    external_links = []
    article_url = None

    for u in urls_data:
        exp_url = u.get("expanded_url")
        if exp_url:
            external_links.append(exp_url)
            # Eğer twitter içi durum linki değilse bu bir dış haber bağlantısıdır
            if not article_url and "twitter.com" not in exp_url and "x.com" not in exp_url:
                article_url = exp_url

    hashtags = [h.get("text") for h in entities.get("hashtags", []) if h.get("text")]

    # Temiz metin: t.co linklerini çıkarılmış veya okunabilir hali
    clean_text = full_text
    # Tweet sonundaki t.co medya linklerini temizle
    clean_text = re.sub(r'https://t\.co/\w+\s*$', '', clean_text).strip()

    # Yazar Bilgisi
    author_info = extract_author_details(tweet)
    author_username = author_info.get("username", "")

    # Gerçek Tweet URL'si
    source_url = f"https://x.com/{author_username}/status/{tweet_id}" if author_username else f"https://x.com/i/web/status/{tweet_id}"

    # Etkileşim Metrikleri
    metrics = {
        "likes": legacy.get("favorite_count", 0),
        "retweets": legacy.get("retweet_count", 0),
        "replies": legacy.get("reply_count", 0),
        "quotes": legacy.get("quote_count", 0),
        "views": tweet.get("views", {}).get("count")
    }

    # Kategori Belirleme
    category_slug = getattr(list_config, "category", "") or "gundem"
    category_name = getattr(list_config, "name", "") or "Gündem"
    list_id = getattr(list_config, "list_id", "")
    list_url = getattr(list_config, "url", f"https://x.com/i/lists/{list_id}")

    # Eksiksiz Firestore Dokümanı
    doc_payload = {
        "tweet_id": tweet_id,
        "text": full_text,
        "clean_text": clean_text,
        "images": images,
        "videos": videos,
        "has_media": bool(images or videos),
        "media_count": len(images) + len(videos),
        "rich_media": rich_media,
        "card": card_info if card_info.get("has_card") else None,
        "quoted_tweet": quoted_data,
        "external_links": external_links,
        "article_url": article_url or card_info.get("url"),
        "hashtags": hashtags,
        "metrics": metrics,
        "source_url": source_url,
        "author": author_info,
        
        # Liste ve Kategori Bilgileri
        "category": category_slug,
        "category_name": category_name,
        "list_name": category_name,
        "list_id": list_id,
        "list_url": list_url,

        # Tarihler & TTL (2 Günlük Silme için)
        "created_at": created_at_raw,
        "published_at": iso_str,
        "published_timestamp": epoch_ts,
        "expires_at": expire_iso,
        "expires_timestamp": expire_ts,
        "retention_days": retention_days
    }

    return doc_payload
