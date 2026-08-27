import json
import os
import sys
import firebase_admin
from firebase_admin import credentials, firestore
from playwright.sync_api import sync_playwright

# --- YAPILANDIRMA ---
LIST_ID = "1975820683461460354"

def get_env_variable(var_name):
    value = os.environ.get(var_name)
    if not value:
        sys.exit(f"KRİTİK HATA: {var_name} bulunamadı!")
    return value

# --- FIREBASE ---
def init_firebase():
    print("-> Firebase başlatılıyor...")
    try:
        cred_dict = json.loads(get_env_variable("FIREBASE_CREDENTIALS"))
        cred = credentials.Certificate(cred_dict)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        sys.exit(f"KRİTİK HATA: Firebase hatası: {e}")

# --- ÇEREZLERİ PLAYWRIGHT FORMATINA ÇEVİR ---
def parse_cookies_for_browser():
    cookies_str = get_env_variable("TWITTER_COOKIES")
    try:
        cookies_raw = json.loads(cookies_str)
    except Exception:
        sys.exit("HATA: Çerezler JSON formatında değil!")

    cookie_dict = {}
    if isinstance(cookies_raw, list):
        for c in cookies_raw:
            if "name" in c and "value" in c:
                cookie_dict[c["name"]] = c["value"]
    elif isinstance(cookies_raw, dict):
        cookie_dict = cookies_raw

    pw_cookies = []
    for k, v in cookie_dict.items():
        pw_cookies.append({
            "name": k,
            "value": v,
            "domain": ".x.com",
            "path": "/"
        })
    return pw_cookies

# --- GÖRÜNMEZ TARAYICI İLE VERİ YAKALAMA ---
def fetch_tweets_via_browser(pw_cookies):
    print("-> Görünmez Tarayıcı (Playwright) başlatılıyor...")
    captured_data = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        context.add_cookies(pw_cookies)
        page = context.new_page()

        # Ağ isteklerini havada dinle (Intercept)
        def handle_response(response):
            nonlocal captured_data
            if "ListLatestTweetsTimeline" in response.url and response.status == 200:
                if response.request.method == "GET":
                    try:
                        print("-> Başarılı! Arka plandaki API JSON verisi yakalandı.")
                        captured_data = response.json()
                    except Exception:
                        pass

        page.on("response", handle_response)
        
        print(f"-> X.com adresinde {LIST_ID} numaralı listeye gidiliyor...")
        try:
            page.goto(f"https://x.com/i/lists/{LIST_ID}", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(6000)  # JS'in API'ye istek atması için süre tanı
        except Exception as e:
            print(f"-> Sayfa yüklenirken zaman aşımı oldu ama veri yakalanmış olabilir: {e}")
        
        browser.close()

    if not captured_data:
        sys.exit("KRİTİK HATA: Tarayıcı açıldı ama 'ListLatestTweetsTimeline' JSON verisi yakalanamadı. Çerezlerin patlamış olabilir.")
    
    return captured_data

# --- ANA İŞLEM ---
def main():
    db = init_firebase()
    pw_cookies = parse_cookies_for_browser()
    data = fetch_tweets_via_browser(pw_cookies)

    try:
        instructions = data["data"]["list"]["tweets_timeline"]["timeline"]["instructions"]
    except KeyError:
        sys.exit("KRİTİK HATA: Yakalanan veri beklenen X JSON formatında değil.")

    entries = []
    for inst in instructions:
        if inst.get("type") == "TimelineAddEntries":
            entries = inst.get("entries", [])
            break

    if not entries:
        print("-> İşlenecek yeni tweet bulunamadı.")
        return

    print(f"-> Analiz edilen haber sayısı: {len(entries)}")
    saved_count, updated_count = 0, 0

    for entry in entries:
        content = entry.get("content", {}).get("itemContent", {}).get("tweet_results", {}).get("result", {})
        if not content: continue

        tweet = content.get("tweet", content) if content.get("__typename") == "TweetWithVisibilityResults" else content
        tweet_id = tweet.get("rest_id")
        if not tweet_id: continue

        legacy = tweet.get("legacy", {})
        
        # Medya toplama
        images, videos = [], []
        media_list = legacy.get("extended_entities", {}).get("media", []) or legacy.get("entities", {}).get("media", [])
        for m in media_list:
            if m.get("type") == "photo" and m.get("media_url_https"):
                images.append(m["media_url_https"])
            if m.get("type") in ["video", "animated_gif"]:
                variants = m.get("video_info", {}).get("variants", [])
                mp4_variants = [v for v in variants if v.get("content_type") == "video/mp4"]
                if mp4_variants:
                    best_video = max(mp4_variants, key=lambda x: x.get("bitrate", 0))
                    if best_video.get("url"): videos.append(best_video["url"])

        # Yazar bilgisi
        user_legacy = tweet.get("core", {}).get("user_results", {}).get("result", {}).get("legacy", {})
        
        doc_data = {
            "tweet_id": tweet_id,
            "text": legacy.get("full_text", ""),
            "images": list(set(images)),
            "videos": list(set(videos)),
            "has_media": bool(images or videos),
            "media_count": len(images) + len(videos),
            "created_at": legacy.get("created_at", ""),
            "list_id": LIST_ID,
            "source_url": f"https://x.com/i/web/status/{tweet_id}",
            "author": {
                "name": user_legacy.get("name", ""),
                "screen_name": user_legacy.get("screen_name", ""),
                "profile_image_url": user_legacy.get("profile_image_url_https", "")
            },
            "updated_at": firestore.SERVER_TIMESTAMP
        }

        # Firestore'a kaydet
        doc_ref = db.collection("haberler").document(tweet_id)
        if doc_ref.get().exists:
            doc_ref.set(doc_data, merge=True)
            updated_count += 1
        else:
            doc_ref.set(doc_data)
            saved_count += 1

    print("-" * 30)
    print(f"İŞLEM BİTTİ. Yeni: {saved_count} | Güncellenen: {updated_count}")
    print("-" * 30)

if __name__ == "__main__":
    main()
