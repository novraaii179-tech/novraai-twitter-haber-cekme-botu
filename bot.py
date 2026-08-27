import json
import os
import requests
import firebase_admin
from firebase_admin import credentials, firestore

# 1. Firebase Başlatma
firebase_json_str = os.environ.get("FIREBASE_CREDENTIALS")
if not firebase_json_str:
    raise ValueError("FIREBASE_CREDENTIALS secret verisi bulunamadı!")

cred_dict = json.loads(firebase_json_str)
cred = credentials.Certificate(cred_dict)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

LIST_ID = "1975820683461460354"

def parse_cookies():
    cookies_str = os.environ.get("TWITTER_COOKIES")
    if not cookies_str:
        raise ValueError("TWITTER_COOKIES bulunamadı!")

    cookies_raw = json.loads(cookies_str)
    cookie_dict = {}

    if isinstance(cookies_raw, list):
        for c in cookies_raw:
            if "name" in c and "value" in c:
                cookie_dict[c["name"]] = c["value"]
    elif isinstance(cookies_raw, dict):
        cookie_dict = cookies_raw

    return cookie_dict

def fetch_and_save():
    cookie_dict = parse_cookies()
    ct0 = cookie_dict.get("ct0", "")
    auth_token = cookie_dict.get("auth_token", "")

    if not ct0 or not auth_token:
        print("UYARI: Çerezlerde ct0 veya auth_token eksik! Lütfen x.com'dan yeni çerez export edin.")

    cookie_header = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])

    headers = {
        "authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",
        "x-csrf-token": ct0,
        "cookie": cookie_header,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "content-type": "application/json"
    }

    # Twitter GraphQL Liste Sorgusu
    url = "https://x.com/i/api/graphql/2V_Up2VGmEti9_iooiTqng/ListLatestTweetsTimeline"
    
    variables = {
        "listId": LIST_ID,
        "count": 100
    }
    
    features = {
        "responsive_web_graphql_exclude_directive_enabled": True,
        "verified_phone_label_enabled": False,
        "responsive_web_home_pinned_timelines_enabled": True,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_timeline_navigation_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "c9s_tweet_anatomy_moderator_badge_enabled": True,
        "tweetypie_unmention_optimization_enabled": True,
        "responsive_web_edit_tweet_api_enabled": True,
        "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
        "view_counts_everywhere_api_enabled": True,
        "longform_notetweets_consumption_enabled": True,
        "responsive_web_twitter_article_tweet_consumption_enabled": True,
        "tweet_awards_web_tipping_enabled": False,
        "freedom_of_speech_not_reach_fetch_enabled": True,
        "standardized_nudges_misinfo": True,
        "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
        "rweb_video_timestamps_enabled": True,
        "longform_notetweets_rich_text_read_enabled": True,
        "longform_notetweets_inline_media_enabled": True,
        "responsive_web_enhance_cards_enabled": False
    }

    params = {
        "variables": json.dumps(variables),
        "features": json.dumps(features)
    }

    print(f"Liste taranıyor: {LIST_ID}...")
    response = requests.get(url, headers=headers, params=params)

    if response.status_code != 200:
        print(f"Bağlantı Hatası: {response.status_code} - {response.text[:200]}")
        return

    data = response.json()
    
    try:
        instructions = data["data"]["list"]["tweets_timeline"]["timeline"]["instructions"]
    except KeyError:
        print("Hata: Liste akışı çözümlenemedi. Çerezlerinizi yenilemeniz gerekebilir.")
        return

    entries = []
    for inst in instructions:
        if inst.get("type") == "TimelineAddEntries":
            entries = inst.get("entries", [])
            break

    if not entries:
        print("İşlenecek tweet bulunamadı.")
        return

    saved_count = 0
    updated_count = 0

    for entry in entries:
        content = entry.get("content", {})
        item_content = content.get("itemContent", {})
        tweet_results = item_content.get("tweet_results", {})
        result = tweet_results.get("result", {})

        if not result:
            continue

        if result.get("__typename") == "TweetWithVisibilityResults":
            tweet = result.get("tweet", {})
        else:
            tweet = result

        tweet_id = tweet.get("rest_id")
        if not tweet_id:
            continue

        legacy = tweet.get("legacy", {})
        text = legacy.get("full_text", "")
        created_at = legacy.get("created_at", "")

        images = []
        videos = []

        # Görsel ve Video ayrıştırma
        media_list = legacy.get("extended_entities", {}).get("media", []) or legacy.get("entities", {}).get("media", [])
        for m in media_list:
            # Fotoğraf
            if m.get("type") == "photo" and m.get("media_url_https"):
                images.append(m["media_url_https"])
            
            # Video ve GIF
            if m.get("type") in ["video", "animated_gif"]:
                variants = m.get("video_info", {}).get("variants", [])
                mp4_variants = [v for v in variants if v.get("content_type") == "video/mp4"]
                if mp4_variants:
                    best_video = max(mp4_variants, key=lambda x: x.get("bitrate", 0))
                    if best_video.get("url"):
                        videos.append(best_video["url"])
                elif m.get("media_url_https"):
                    images.append(m["media_url_https"])

        # Yazar Detayları
        user_result = tweet.get("core", {}).get("user_results", {}).get("result", {})
        user_legacy = user_result.get("legacy", {})
        author = {
            "name": user_legacy.get("name", ""),
            "screen_name": user_legacy.get("screen_name", ""),
            "profile_image_url": user_legacy.get("profile_image_url_https", "")
        }

        doc_data = {
            "tweet_id": tweet_id,
            "text": text,
            "images": list(set(images)),
            "videos": list(set(videos)),
            "has_media": bool(images or videos),
            "media_count": len(images) + len(videos),
            "created_at": created_at,
            "list_id": LIST_ID,
            "source_url": f"https://x.com/i/web/status/{tweet_id}",
            "author": author,
            "updated_at": firestore.SERVER_TIMESTAMP
        }

        doc_ref = db.collection("haberler").document(tweet_id)
        doc_snapshot = doc_ref.get()

        if doc_snapshot.exists:
            doc_ref.set(doc_data, merge=True)
            updated_count += 1
        else:
            doc_ref.set(doc_data)
            saved_count += 1

    print(f"İşlem Tamamlandı! Yeni eklenen haber: {saved_count}, Güncellenen: {updated_count}")

if __name__ == "__main__":
    fetch_and_save()
