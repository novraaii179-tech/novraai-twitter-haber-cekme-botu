import json
import os
import sys

import firebase_admin
from firebase_admin import credentials, firestore
from playwright.sync_api import sync_playwright


# --------------------------------------------------
# YAPILANDIRMA
# --------------------------------------------------

LIST_ID = "1975820683461460354"


def get_env_variable(var_name):
    value = os.environ.get(var_name)

    if not value:
        sys.exit(
            f"KRİTİK HATA: {var_name} bulunamadı!"
        )

    return value


# --------------------------------------------------
# FIREBASE
# --------------------------------------------------

def init_firebase():
    print("-> Firebase başlatılıyor...")

    try:
        cred_dict = json.loads(
            get_env_variable("FIREBASE_CREDENTIALS")
        )

        cred = credentials.Certificate(
            cred_dict
        )

        if not firebase_admin._apps:
            firebase_admin.initialize_app(
                cred
            )

        return firestore.client()

    except Exception as e:
        sys.exit(
            f"KRİTİK HATA: Firebase hatası: {e}"
        )


# --------------------------------------------------
# X ÇEREZLERİNİ PLAYWRIGHT FORMATINA ÇEVİR
# --------------------------------------------------

def parse_cookies_for_browser():

    cookies_str = get_env_variable(
        "TWITTER_COOKIES"
    )

    try:
        cookies_raw = json.loads(
            cookies_str
        )

    except Exception:
        sys.exit(
            "HATA: Çerezler JSON formatında değil!"
        )

    cookie_dict = {}

    if isinstance(cookies_raw, list):

        for cookie in cookies_raw:

            if (
                "name" in cookie
                and "value" in cookie
            ):
                cookie_dict[
                    cookie["name"]
                ] = cookie["value"]

    elif isinstance(
        cookies_raw,
        dict
    ):
        cookie_dict = cookies_raw

    pw_cookies = []

    for key, value in cookie_dict.items():

        pw_cookies.append(
            {
                "name": key,
                "value": value,
                "domain": ".x.com",
                "path": "/"
            }
        )

    return pw_cookies


# --------------------------------------------------
# PLAYWRIGHT İLE X VERİSİ YAKALAMA
# --------------------------------------------------

def fetch_tweets_via_browser(
    pw_cookies
):

    print(
        "-> Görünmez Tarayıcı "
        "(Playwright) başlatılıyor..."
    )

    captured_data = None

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(

            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/126.0.0.0 "
                "Safari/537.36"
            ),

            viewport={
                "width": 1280,
                "height": 720
            }
        )

        context.add_cookies(
            pw_cookies
        )

        page = context.new_page()

        # ------------------------------------------
        # X API cevabını yakala
        # ------------------------------------------

        def handle_response(response):

            nonlocal captured_data

            if (
                "ListLatestTweetsTimeline"
                in response.url
                and response.status == 200
                and response.request.method == "GET"
            ):

                try:

                    print(
                        "-> Başarılı! "
                        "Arka plandaki API JSON "
                        "verisi yakalandı."
                    )

                    captured_data = (
                        response.json()
                    )

                except Exception:
                    pass

        page.on(
            "response",
            handle_response
        )

        print(
            f"-> X.com adresinde "
            f"{LIST_ID} numaralı "
            "listeye gidiliyor..."
        )

        try:

            page.goto(
                f"https://x.com/i/lists/{LIST_ID}",
                wait_until="networkidle",
                timeout=30000
            )

            # X'in API isteğini yapması için
            # biraz süre ver.
            page.wait_for_timeout(
                6000
            )

        except Exception as e:

            print(
                "-> Sayfa yüklenirken "
                "zaman aşımı oldu ancak "
                "veri yakalanmış olabilir: "
                f"{e}"
            )

        browser.close()

    if not captured_data:

        sys.exit(
            "KRİTİK HATA: Tarayıcı açıldı "
            "ama 'ListLatestTweetsTimeline' "
            "JSON verisi yakalanamadı. "
            "Çerezler geçersiz olabilir."
        )

    return captured_data


# --------------------------------------------------
# ANA İŞLEM
# --------------------------------------------------

def main():

    db = init_firebase()

    pw_cookies = (
        parse_cookies_for_browser()
    )

    data = fetch_tweets_via_browser(
        pw_cookies
    )

    # ----------------------------------------------
    # Timeline verisini bul
    # ----------------------------------------------

    try:

        instructions = (
            data["data"]
            ["list"]
            ["tweets_timeline"]
            ["timeline"]
            ["instructions"]
        )

    except KeyError:

        sys.exit(
            "KRİTİK HATA: Yakalanan veri "
            "beklenen X JSON formatında değil."
        )

    entries = []

    for instruction in instructions:

        if (
            instruction.get("type")
            == "TimelineAddEntries"
        ):

            entries = instruction.get(
                "entries",
                []
            )

            break

    if not entries:

        print(
            "-> İşlenecek yeni tweet "
            "bulunamadı."
        )

        return

    print(
        f"-> Analiz edilen haber sayısı: "
        f"{len(entries)}"
    )

    saved_count = 0
    updated_count = 0

    # ----------------------------------------------
    # TWEETLERİ İŞLE
    # ----------------------------------------------

    for entry in entries:

        content = (
            entry
            .get("content", {})
            .get("itemContent", {})
            .get("tweet_results", {})
            .get("result", {})
        )

        if not content:
            continue

        # Bazı X cevaplarında gerçek Tweet
        # "tweet" alanının içinde geliyor.
        if (
            content.get("__typename")
            == "TweetWithVisibilityResults"
        ):

            tweet = content.get(
                "tweet",
                {}
            )

        else:
            tweet = content

        tweet_id = tweet.get(
            "rest_id"
        )

        if not tweet_id:
            continue

        legacy = tweet.get(
            "legacy",
            {}
        )

        # ------------------------------------------
        # MEDYA
        # ------------------------------------------

        images = []
        videos = []

        media_list = (
            legacy
            .get(
                "extended_entities",
                {}
            )
            .get(
                "media",
                []
            )
        )

        if not media_list:

            media_list = (
                legacy
                .get(
                    "entities",
                    {}
                )
                .get(
                    "media",
                    []
                )
            )

        for media in media_list:

            media_type = media.get(
                "type"
            )

            # Fotoğraf
            if (
                media_type == "photo"
                and media.get(
                    "media_url_https"
                )
            ):

                images.append(
                    media[
                        "media_url_https"
                    ]
                )

            # Video / GIF
            elif media_type in [
                "video",
                "animated_gif"
            ]:

                variants = (
                    media
                    .get(
                        "video_info",
                        {}
                    )
                    .get(
                        "variants",
                        []
                    )
                )

                mp4_variants = [
                    variant
                    for variant in variants
                    if (
                        variant.get(
                            "content_type"
                        )
                        == "video/mp4"
                    )
                ]

                if mp4_variants:

                    best_video = max(
                        mp4_variants,
                        key=lambda item:
                        item.get(
                            "bitrate",
                            0
                        )
                    )

                    video_url = (
                        best_video.get(
                            "url"
                        )
                    )

                    if video_url:
                        videos.append(
                            video_url
                        )

        # Tekrar eden medyaları kaldır
        images = list(
            dict.fromkeys(images)
        )

        videos = list(
            dict.fromkeys(videos)
        )

        # ------------------------------------------
        # YAZAR / KAYNAK BİLGİSİ
        # ------------------------------------------

        user_result = (
            tweet
            .get("core", {})
            .get("user_results", {})
            .get("result", {})
        )

        user_legacy = (
            user_result.get(
                "legacy",
                {}
            )
        )

        user_core = (
            user_result.get(
                "core",
                {}
            )
        )

        # X'in farklı JSON yapılarında
        # isim legacy veya core altında olabilir.
        author_name = (

            user_legacy.get("name")

            or user_core.get("name")

            or ""
        )

        # Kullanıcı adı
        author_username = (

            user_legacy.get(
                "screen_name"
            )

            or user_core.get(
                "screen_name"
            )

            or ""
        )

        # Bazı yeni cevaplarda screen_name
        # doğrudan core içindeki user_results
        # yapısından farklı gelebilir.
        if not author_username:

            author_username = (
                user_result
                .get(
                    "screen_name",
                    ""
                )
            )

        # Profil resmi
        profile_image_url = (

            user_legacy.get(
                "profile_image_url_https"
            )

            or (
                user_result
                .get(
                    "avatar",
                    {}
                )
                .get(
                    "image_url",
                    ""
                )
            )

            or ""
        )

        # ------------------------------------------
        # GERÇEK X KAYNAK URL'Sİ
        # ------------------------------------------

        if author_username:

            source_url = (
                f"https://x.com/"
                f"{author_username}/"
                f"status/{tweet_id}"
            )

        else:

            # Username alınamazsa bile
            # tweet adresi çalışmaya devam eder.
            source_url = (
                f"https://x.com/i/web/"
                f"status/{tweet_id}"
            )

        # Debug
        print(
            f"-> Kaynak: "
            f"{author_name or 'Bilinmiyor'}"
            f" | "
            f"@{author_username or 'Bilinmiyor'}"
            f" | "
            f"{source_url}"
        )

        # ------------------------------------------
        # FIRESTORE VERİSİ
        # ------------------------------------------

        doc_data = {

            "tweet_id":
                tweet_id,

            "text":
                legacy.get(
                    "full_text",
                    ""
                ),

            "images":
                images,

            "videos":
                videos,

            "has_media":
                bool(
                    images
                    or videos
                ),

            "media_count":
                len(images)
                + len(videos),

            "created_at":
                legacy.get(
                    "created_at",
                    ""
                ),

            "list_id":
                LIST_ID,

            # Gerçek X linki
            "source_url":
                source_url,

            # Kaynak / yazar
            "author": {

                "name":
                    author_name,

                # Android tarafında
                # kullanılacak alan.
                "username":
                    author_username,

                # Eski kodlarla
                # uyumluluk.
                "screen_name":
                    author_username,

                "profile_image_url":
                    profile_image_url
            },

            "updated_at":
                firestore.SERVER_TIMESTAMP
        }

        # ------------------------------------------
        # FIRESTORE'A KAYDET
        # ------------------------------------------

        doc_ref = (
            db
            .collection("haberler")
            .document(tweet_id)
        )

        try:

            existing_doc = (
                doc_ref.get()
            )

            if existing_doc.exists:

                doc_ref.set(
                    doc_data,
                    merge=True
                )

                updated_count += 1

            else:

                doc_ref.set(
                    doc_data
                )

                saved_count += 1

        except Exception as e:

            print(
                f"-> Firestore kayıt hatası "
                f"({tweet_id}): {e}"
            )

    # ----------------------------------------------
    # SONUÇ
    # ----------------------------------------------

    print("-" * 50)

    print(
        "İŞLEM BİTTİ. "
        f"Yeni: {saved_count} | "
        f"Güncellenen: {updated_count}"
    )

    print("-" * 50)


if __name__ == "__main__":
    main()
