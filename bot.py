import argparse
import sys
import time
from typing import Dict, Any, List, Optional
from playwright.sync_api import sync_playwright

from config import Config, TwitterListConfig
from extractor import extract_full_news_data
from database import Database


# --------------------------------------------------
# PLAYWRIGHT İLE X (TWITTER) LİSTE VERİSİ YAKALAMA
# --------------------------------------------------

def fetch_list_timeline_data(
    page, 
    list_config: TwitterListConfig
) -> Optional[Dict[str, Any]]:
    """
    Belirtilen X liste sayfasına gider ve arka planda tetiklenen
    ListLatestTweetsTimeline GraphQL JSON yanıtını yakalar.
    """
    captured_data = None
    list_url = list_config.url

    def handle_response(response):
        nonlocal captured_data
        if (
            "ListLatestTweetsTimeline" in response.url
            and response.status == 200
            and response.request.method == "GET"
        ):
            try:
                captured_data = response.json()
            except Exception:
                pass

    page.on("response", handle_response)

    print(f"\n-> [{list_config.category.upper()}] Listeye gidiliyor: {list_url}")

    try:
        page.goto(list_url, wait_until="networkidle", timeout=35000)
        # Verilerin ve medya API çağrılarının tamamlanması için bekle
        page.wait_for_timeout(6000)
    except Exception as e:
        print(f"-> Sayfa yüklenirken zaman aşımı oldu (veri yine de yakalanmış olabilir): {e}")

    # Listener'ı temizle
    try:
        page.remove_listener("response", handle_response)
    except Exception:
        pass

    return captured_data


# --------------------------------------------------
# LİSTE BAZLI TWEETLERİ İŞLE VE KAYDET
# --------------------------------------------------

def process_list(
    db: Database, 
    captured_data: Dict[str, Any], 
    list_config: TwitterListConfig
) -> tuple[int, int]:
    """
    Yakalanan JSON verisindeki tweetleri, görselleri ve videoları ayıklar,
    Firebase Firestore'a liste/kategori bilgisiyle kaydeder.
    """
    try:
        list_obj = captured_data.get("data", {}).get("list", {})
        
        # Eğer konfigürasyonda isim belirtilmemişse X'teki liste adını otomatik al
        x_list_name = list_obj.get("name")
        if x_list_name and not list_config.name:
            list_config.name = x_list_name
            if not list_config.category:
                from config import slugify
                list_config.category = slugify(x_list_name)

        instructions = (
            list_obj
            .get("tweets_timeline", {})
            .get("timeline", {})
            .get("instructions", [])
        )
    except KeyError:
        print("[HATA] Yakalanan veri beklenen X JSON formatında değil.")
        return 0, 0

    entries = []
    for instruction in instructions:
        if instruction.get("type") == "TimelineAddEntries":
            entries = instruction.get("entries", [])
            break

    if not entries:
        print(f"-> [{list_config.name or list_config.list_id}] İşlenecek yeni tweet bulunamadı.")
        return 0, 0

    print(f"-> Bulunan tweet sayısı: {len(entries)}")

    saved_count = 0
    updated_count = 0

    for entry in entries:
        # Haberi, tüm görselleri, videoları ve metadata'yı çıkar
        news_item = extract_full_news_data(
            entry, 
            list_config, 
            retention_days=Config.RETENTION_DAYS
        )

        if not news_item:
            continue

        tweet_id = news_item["tweet_id"]
        author = news_item.get("author", {})
        media_count = news_item.get("media_count", 0)
        img_count = len(news_item.get("images", []))
        vid_count = len(news_item.get("videos", []))

        print(
            f"   📰 [{news_item['category']}] @{author.get('username') or 'anonim'}: "
            f"{news_item.get('clean_text', '')[:65]}... "
            f"(📸 {img_count} resim | 🎥 {vid_count} video)"
        )

        # Firestore'a kaydet
        is_new, success = db.save_news(news_item)
        if success:
            if is_new:
                saved_count += 1
            else:
                updated_count += 1

    return saved_count, updated_count


# --------------------------------------------------
# ANA AKIŞ
# --------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Twitter'dan Firebase Firestore'a Otomatik Haber Çekme ve Temizleme Botu (v1.4)"
    )
    parser.add_argument("--cleanup-only", action="store_true", help="Sadece 2 günden eski haberleri siler")
    parser.add_argument("--no-cleanup", action="store_true", help="2 günlük otomatik temizleme adımını atlar")
    parser.add_argument("--list", type=str, help="Sadece belirli bir liste URL'si veya ID'si için çalıştır")
    args = parser.parse_args()

    print("=" * 65)
    print("🚀 NOVRA AI - TWITTER HABER ÇEKME VE YÖNETİM BOTU (v1.4)")
    print("   Geliştiriciler: Muhammed Yasin KORKUT & Beyza KARAKAŞ")
    print("=" * 65)

    # 1. Veritabanını Başlat
    db = Database()

    # Eğer sadece temizleme istendiyse
    if args.cleanup_only:
        db.delete_expired_news(retention_days=Config.RETENTION_DAYS)
        print("-> Temizleme işlemi tamamlandı. Çıkılıyor.")
        return

    # 2. Takip Edilecek Listeleri Belirle
    if args.list:
        from config import extract_list_id, slugify
        list_id = extract_list_id(args.list)
        if not list_id:
            sys.exit(f"HATA: Geçersiz liste parametresi: {args.list}")
        lists_to_fetch = [
            TwitterListConfig(
                list_id=list_id, 
                url=args.list if args.list.startswith("http") else f"https://x.com/i/lists/{list_id}",
                name="Özel Liste",
                category="ozel"
            )
        ]
    else:
        lists_to_fetch = Config.get_twitter_lists()

    print(f"-> Toplam {len(lists_to_fetch)} adet X listesi taranacak.")
    for idx, l in enumerate(lists_to_fetch, 1):
        print(f"   {idx}. ID: {l.list_id} | Kategori: {l.category or 'Otomatik'} | URL: {l.url}")

    # 3. Çerezleri Al
    pw_cookies = Config.get_twitter_cookies()

    total_saved = 0
    total_updated = 0

    # 4. Playwright ile Tarayıcıyı Başlat ve Listeleri Gez
    print("\n-> Görünmez Tarayıcı (Playwright Chromium) hazırlanıyor...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720}
        )
        context.add_cookies(pw_cookies)
        page = context.new_page()

        for l_cfg in lists_to_fetch:
            try:
                captured_json = fetch_list_timeline_data(page, l_cfg)
                if not captured_json:
                    print(f"[UYARI] '{l_cfg.url}' için veri yakalanamadı. Çerezleri veya liste izinlerini kontrol edin.")
                    continue

                saved, updated = process_list(db, captured_json, l_cfg)
                total_saved += saved
                total_updated += updated

                # Listeler arası nazik bekleme
                time.sleep(2)
            except Exception as e:
                print(f"[HATA] Liste işlenirken beklenmeyen hata ({l_cfg.url}): {e}")

        browser.close()

    print("\n" + "=" * 65)
    print(f"✅ ÇEKME İŞLEMİ TAMAMLANDI: {total_saved} Yeni Haber | {total_updated} Güncellendi")
    print("=" * 65)

    # 5. 2 Günden Eski Haberleri Otomatik Temizle
    if Config.AUTO_CLEANUP_ENABLED and not args.no_cleanup:
        db.delete_expired_news(retention_days=Config.RETENTION_DAYS)


if __name__ == "__main__":
    main()
