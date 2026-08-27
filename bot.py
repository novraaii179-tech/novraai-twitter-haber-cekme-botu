import json
import os
import re
import sys
import requests
import firebase_admin
from firebase_admin import credentials, firestore

# --- 1. YAPILANDIRMA VE GÜVENLİK ---
LIST_ID = "1975820683461460354"

def get_env_variable(var_name):
    value = os.environ.get(var_name)
    if not value:
        sys.exit(f"KRİTİK HATA: {var_name} GitHub Secrets içinde bulunamadı!")
    return value

# --- 2. FIREBASE BAĞLANTISI ---
def init_firebase():
    print("-> Firebase başlatılıyor...")
    firebase_json_str = get_env_variable("FIREBASE_CREDENTIALS")
    try:
        cred_dict = json.loads(firebase_json_str)
        cred = credentials.Certificate(cred_dict)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        print("-> Firebase bağlantısı başarılı.")
        return firestore.client()
    except Exception as e:
        sys.exit(f"KRİTİK HATA: Firebase kimlik doğrulaması başarısız! Hata: {e}")

# --- 3. X ÇEREZ YÖNETİMİ ---
def parse_cookies():
    cookies_str = get_env_variable("TWITTER_COOKIES")
    try:
        cookies_raw = json.loads(cookies_str)
    except json.JSONDecodeError:
        sys.exit("KRİTİK HATA: TWITTER_COOKIES geçerli bir JSON formatında değil!")

    cookie_dict = {}
    if isinstance(cookies_raw, list):
        for c in cookies_raw:
            if "name" in c and "value" in c:
                cookie_dict[c["name"]] = c["value"]
    elif isinstance(cookies_raw, dict):
        cookie_dict = cookies_raw

    if "ct0" not in cookie_dict or "auth_token" not in cookie_dict:
        sys.exit("KRİTİK HATA: Çerezler içinde 'ct0' veya 'auth_token' bulunamadı. Oturum düşmüş olabilir.")

    return cookie_dict

# --- 4. DİNAMİK QUERY ID BULUCU ---
def get_live_query_id(session, headers):
    print("-> X (Twitter) JS dosyaları taranıyor...")
    try:
        # ANA SAYFA YERİNE DOĞRUDAN LİSTE SAYFASINI TARIYORUZ
        list_url = f"https://x.com/i/lists/{LIST_ID}"
        res = session.get(list_url, headers={"User-Agent": headers["user-agent"]}, timeout=15)
        
        # Daha esnek bir regex ile tüm twimg JS dosyalarını yakalayalım
        js_files = re.findall(r'https://abs[-0-9a-z]*\.twimg\.com/[^"\'\s]+\.js', res.text)
        print(f"-> Toplam {len(set(js_files))} adet JS dosyası bulundu, taranıyor...")
        
        for js_url in set(js_files):
            try:
                js_res = session.get(js_url, headers={"User-Agent": headers["user-agent"]}, timeout=10)
                
                # ListLatestTweetsTimeline operasyonunu içeren dosyayı bulduğumuzda ID'yi çek
                if "ListLatestTweetsTimeline" in js_res.text:
                    match = re.search(r'queryId:"([^"]+)"[^}]*operationName:"ListLatestTweetsTimeline"', js_res.text)
                    if not match:
                        match = re.search(r'operationName:"ListLatestTweetsTimeline"[^}]*queryId:"([^"]+)"', js_res.text)
                    
                    if match:
                        query_id = match.group(1)
                        file_name = js_url.split('/')[-1]
                        print(f"-> Başarılı! Güncel Query ID bulundu: {query_id} (Dosya: {file_name})")
                        return query_id
            except requests.exceptions.RequestException:
                # Bazı JS dosyaları zaman aşımına uğrarsa veya yüklenemezse döngüye devam et
                continue
                    
    except Exception as e:
        sys.exit(f"KRİTİK HATA: JS tarama sırasında ağ hatası oluştu: {e}")
    
    sys.exit("KRİTİK HATA: 'ListLatestTweetsTimeline' için güncel Query ID bulunamadı. X API yapısı değişmiş olabilir.")

# --- 5. ANA İŞLEM AKIŞI ---
def main():
    db = init_firebase()
    session = requests.Session()
    cookie_dict = parse_cookies()
    
    cookie_header = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
    
    headers = {
        "authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",
        "x-csrf-token": cookie_dict["ct0"],
        "cookie": cookie_header,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "content-type": "application/json"
    }

    # Güncel ID'yi bul
    query_id = get_live_query_id(session, headers)
    
    url = f"https://x.com/i/api/graphql/{query_id}/ListLatestTweetsTimeline"
    
    variables = {"listId": LIST_ID, "count": 100}
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
        "responsive_web_enhance_cards_enabled": False,
        "articles_preview_enabled": True,
        "rweb_tipjar_consumption_enabled": True
    }

    print("-> X bağlantısı kuruluyor, haberler çekiliyor...")
    response = session.get(url, headers=headers, params={"variables": json.dumps(variables), "features": json.dumps(features)})

    if response.status_code != 200:
        sys.exit(f"KRİTİK HATA: X API bağlantı hatası! HTTP {response.status_code}\nDetay: {response.text[:300]}")
    
    print("-> X bağlantısı başarılı. JSON verisi çözümleniyor...")
    data = response.json()
    
    try:
        instructions = data["data"]["list"]["tweets_timeline"]["timeline"]["instructions"]
    except KeyError:
        sys.exit(f"KRİTİK HATA: X JSON formatı beklendiği gibi değil. Veri: {str(data)[:200]}")

    entries = []
    for inst in instructions:
        if inst.get("type") == "TimelineAddEntries":
            entries = inst.get("entries", [])
            break

    if not entries:
        print("-> İşlenecek yeni tweet bulunamadı. Sistem sonlanıyor.")
        return

    print(f"-> Analiz edilen toplam haber (tweet) sayısı: {len(entries)}")
    
    saved_count = 0
    updated_count = 0

    print("-> Firestore'a yazma işlemi başlıyor...")
    for entry in entries:
        content = entry.get("content", {}).get("itemContent", {}).get("tweet_results", {}).get("result", {})
        if not content:
            continue

        tweet = content.get("tweet", content) if content.get("__typename") == "TweetWithVisibilityResults" else content
        tweet_id = tweet.get("rest_id")
        if not tweet_id:
            continue

        legacy = tweet.get("legacy", {})
        text = legacy.get("full_text", "")
        created_at = legacy.get("created_at", "")

        images = []
        videos = []

        media_list = legacy.get("extended_entities", {}).get("media", []) or legacy.get("entities", {}).get("media", [])
        for m in media_list:
            if m.get("type") == "photo" and m.get("media_url_https"):
                images.append(m["media_url_https"])
            
            if m.get("type") in ["video", "animated_gif"]:
                variants = m.get("video_info", {}).get("variants", [])
                mp4_variants = [v for v in variants if v.get("content_type") == "video/mp4"]
                if mp4_variants:
                    best_video = max(mp4_variants, key=lambda x: x.get("bitrate", 0))
                    if best_video.get("url"):
                        videos.append(best_video["url"])
                elif m.get("media_url_https"):
                    images.append(m["media_url_https"])

        user_legacy = tweet.get("core", {}).get("user_results", {}).get("result", {}).get("legacy", {})
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
        if doc_ref.get().exists:
            doc_ref.set(doc_data, merge=True)
            updated_count += 1
        else:
            doc_ref.set(doc_data)
            saved_count += 1

    print("-" * 30)
    print("İŞLEM ÖZETİ:")
    print(f"-> Yeni Eklenen Haber: {saved_count}")
    print(f"-> Güncellenen Haber: {updated_count}")
    print("-" * 30)

if __name__ == "__main__":
    main()
