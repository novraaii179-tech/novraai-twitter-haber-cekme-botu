import asyncio
import json
import os
import firebase_admin
from firebase_admin import credentials, firestore
from twikit import Client

# 1. Firebase Başlatma
firebase_json_str = os.environ.get("FIREBASE_CREDENTIALS")
if not firebase_json_str:
    raise ValueError("FIREBASE_CREDENTIALS secret bulunamadı!")

cred_dict = json.loads(firebase_json_str)
cred = credentials.Certificate(cred_dict)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Hedef X/Twitter Liste ID'si
LIST_ID = "1975820683461460354"

async def fetch_and_save():
    # Dil en-US olarak ayarlandığında Twitter şifreleme anahtarları sorunsuz çözülür
    client = Client('en-US')

    # 2. X/Twitter Çerezlerini Yükleme
    cookies_str = os.environ.get("TWITTER_COOKIES")
    if not cookies_str:
        print("HATA: TWITTER_COOKIES bulunamadı!")
        return

    cookies_raw = json.loads(cookies_str)
    if isinstance(cookies_raw, list):
        cookie_dict = {c['name']: c['value'] for c in cookies_raw if 'name' in c and 'value' in c}
        client.set_cookies(cookie_dict)
    elif isinstance(cookies_raw, dict):
        client.set_cookies(cookies_raw)
    else:
        print("HATA: Çerez formatı tanınamadı.")
        return

    print(f"Liste taranıyor: {LIST_ID}...")

    try:
        # Listeden en son tweetleri al
        tweets = await client.get_list_tweets(LIST_ID, count=100)
    except Exception as e:
        print(f"Tweetler çekilirken hata oluştu: {e}")
        return

    if not tweets:
        print("Listede tweet bulunamadı veya erişilemedi.")
        return

    saved_count = 0
    updated_count = 0

    for tweet in tweets:
        tweet_id = str(tweet.id)
        text = getattr(tweet, 'text', None) or getattr(tweet, 'full_text', '') or ''
        created_at = str(getattr(tweet, 'created_at', ''))

        images = []
        videos = []

        # 3. Görsel ve Video Bağlantılarını Ayrıştırma
        if hasattr(tweet, 'media') and tweet.media:
            for m in tweet.media:
                media_url = getattr(m, 'media_url_https', None) or getattr(m, 'url', None)
                if media_url:
                    images.append(media_url)

                streams = getattr(m, 'streams', None)
                if streams:
                    mp4_streams = [s for s in streams if 'mp4' in s.get('url', '') or s.get('content_type') == 'video/mp4']
                    if mp4_streams:
                        best_video = max(mp4_streams, key=lambda x: x.get('bitrate', 0))
                        if best_video.get('url'):
                            videos.append(best_video.get('url'))

                video_info = getattr(m, 'video_info', None)
                if isinstance(video_info, dict):
                    variants = video_info.get('variants', [])
                    mp4_variants = [v for v in variants if v.get('content_type') == 'video/mp4']
                    if mp4_variants:
                        best_var = max(mp4_variants, key=lambda x: x.get('bitrate', 0) or x.get('bit_rate', 0))
                        if best_var.get('url'):
                            videos.append(best_var.get('url'))

        images = list(dict.fromkeys(images))
        videos = list(dict.fromkeys(videos))

        user_info = {}
        if hasattr(tweet, 'user') and tweet.user:
            user_info = {
                "user_id": str(getattr(tweet.user, 'id', '')),
                "name": getattr(tweet.user, 'name', ''),
                "screen_name": getattr(tweet.user, 'screen_name', ''),
                "profile_image_url": getattr(tweet.user, 'profile_image_url_https', '') or getattr(tweet.user, 'profile_image_url', '')
            }

        doc_data = {
            "tweet_id": tweet_id,
            "text": text,
            "images": images,
            "videos": videos,
            "has_media": bool(images or videos),
            "media_count": len(images) + len(videos),
            "created_at": created_at,
            "list_id": LIST_ID,
            "source_url": f"https://x.com/i/web/status/{tweet_id}",
            "author": user_info,
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
    asyncio.run(fetch_and_save())
