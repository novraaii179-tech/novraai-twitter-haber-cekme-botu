import json
import os
import re
import sys
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TwitterListConfig:
    """X (Twitter) Liste Yapılandırması"""
    list_id: str
    url: str
    name: str = ""
    category: str = ""

    def __post_init__(self):
        if not self.url and self.list_id:
            self.url = f"https://x.com/i/lists/{self.list_id}"
        if not self.category and self.name:
            self.category = slugify(self.name)


def slugify(text: str) -> str:
    """Türkçe karakterleri ve özel sembolleri URL/kategori dostu slug formatına çevirir."""
    if not text:
        return "genel"
    
    char_map = {
        'ç': 'c', 'Ç': 'c',
        'ğ': 'g', 'Ğ': 'g',
        'ı': 'i', 'I': 'i', 'İ': 'i',
        'ö': 'o', 'Ö': 'o',
        'ş': 's', 'Ş': 's',
        'ü': 'u', 'Ü': 'u',
    }
    for tr_char, eng_char in char_map.items():
        text = text.replace(tr_char, eng_char)
    
    text = text.lower()
    text = re.sub(r'[^a-z0-9\-_]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    return text or "genel"


def extract_list_id(url_or_id: str) -> Optional[str]:
    """Bir liste URL'sinden veya metninden numeric liste ID'sini ayıklar."""
    clean_val = str(url_or_id).strip()
    # Doğrudan sayısal ID mi?
    if clean_val.isdigit():
        return clean_val
    # URL içinden ID çıkar: /lists/123456789
    match = re.search(r'lists?/(\d+)', clean_val)
    if match:
        return match.group(1)
    # URL sonunda veya herhangi bir yerde uzun sayı öbeği
    match = re.search(r'(\d{10,25})', clean_val)
    if match:
        return match.group(1)
    return None


class Config:
    """Uygulama Genel Yapılandırması"""
    
    DEFAULT_LIST_ID = "1975820683461460354"
    DEFAULT_LIST_NAME = "Gündem ve Haberler"
    
    # 2 Günden sonra otomatik silme süresi (Gün cinsinden)
    RETENTION_DAYS: int = int(os.environ.get("RETENTION_DAYS", "2"))
    
    # Kayıt Modu:
    # 'both': Hem ana 'haberler' koleksiyonuna (category etiketiyle) hem 'haberler_{kategori}' koleksiyonuna kaydeder.
    # 'single': Yalnızca ana 'haberler' koleksiyonuna kaydeder (category alanı içerir).
    # 'categorized': Sadece kategoriye özel 'haberler_{kategori}' koleksiyonuna kaydeder.
    SAVE_MODE: str = os.environ.get("SAVE_MODE", "both").lower()
    
    # Ana koleksiyon adı
    MAIN_COLLECTION: str = os.environ.get("MAIN_COLLECTION", "haberler")
    
    # Otomatik temizleme aktif mi?
    AUTO_CLEANUP_ENABLED: bool = os.environ.get("AUTO_CLEANUP_ENABLED", "true").lower() in ("true", "1", "yes")

    @classmethod
    def get_firebase_credentials(cls) -> dict:
        """Firebase Servis Hesabı JSON verisini ortam değişkeninden veya dosyadan alır."""
        cred_env = os.environ.get("FIREBASE_CREDENTIALS")
        if cred_env:
            try:
                return json.loads(cred_env)
            except Exception as e:
                sys.exit(f"KRİTİK HATA: FIREBASE_CREDENTIALS geçerli bir JSON değil: {e}")
        
        # Yerel dosya kontrolü
        local_files = ["firebase-key.json", "serviceAccountKey.json", "firebase_credentials.json"]
        for filename in local_files:
            if os.path.exists(filename):
                try:
                    with open(filename, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    sys.exit(f"KRİTİK HATA: {filename} dosyası okunamadı: {e}")
                    
        sys.exit("KRİTİK HATA: FIREBASE_CREDENTIALS ortam değişkeni veya yerel firebase-key.json bulunamadı!")

    @classmethod
    def get_twitter_cookies(cls) -> list:
        """X (Twitter) çerezlerini parse ederek Playwright formatına dönüştürür."""
        cookies_str = os.environ.get("TWITTER_COOKIES")
        if not cookies_str:
            if os.path.exists("cookies.json"):
                with open("cookies.json", "r", encoding="utf-8") as f:
                    cookies_str = f.read()
            else:
                sys.exit("KRİTİK HATA: TWITTER_COOKIES ortam değişkeni veya cookies.json bulunamadı!")

        try:
            cookies_raw = json.loads(cookies_str)
        except Exception as e:
            sys.exit(f"KRİTİK HATA: X çerezleri JSON formatında değil: {e}")

        pw_cookies = []
        if isinstance(cookies_raw, list):
            for cookie in cookies_raw:
                if isinstance(cookie, dict) and "name" in cookie and "value" in cookie:
                    domain = cookie.get("domain", ".x.com")
                    if "twitter.com" in domain:
                        domain = ".x.com"
                    pw_cookies.append({
                        "name": cookie["name"],
                        "value": cookie["value"],
                        "domain": domain if domain.startswith(".") else f".{domain}",
                        "path": cookie.get("path", "/")
                    })
        elif isinstance(cookies_raw, dict):
            for key, value in cookies_raw.items():
                pw_cookies.append({
                    "name": key,
                    "value": str(value),
                    "domain": ".x.com",
                    "path": "/"
                })

        if not pw_cookies:
            sys.exit("KRİTİK HATA: Geçerli X çerezi ayrıştırılamadı!")

        return pw_cookies

    @classmethod
    def get_twitter_lists(cls) -> List[TwitterListConfig]:
        """
        Takip edilecek X listelerini tespit eder:
        1. 'lists.json' dosyası varsa oradan okur.
        2. 'TWITTER_LISTS' veya 'TWITTER_LIST_URLS' ortam değişkeninden okur.
           Örnek format:
             - JSON: '[{"url": "...", "name": "Ekonomi"}]'
             - Virgülle ayrılmış: 'https://x.com/i/lists/123|Gündem, https://x.com/i/lists/456|Ekonomi'
             - Düz URL/ID: '123456789, 987654321'
        3. Hiçbiri yoksa varsayılan DEFAULT_LIST_ID kullanılır.
        """
        lists: List[TwitterListConfig] = []

        # 1. lists.json kontrolü
        if os.path.exists("lists.json"):
            try:
                with open("lists.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                raw_id = extract_list_id(item.get("url") or item.get("id") or item.get("list_id", ""))
                                if raw_id:
                                    name = item.get("name", "")
                                    cat = item.get("category", "") or slugify(name)
                                    url = item.get("url") or f"https://x.com/i/lists/{raw_id}"
                                    lists.append(TwitterListConfig(list_id=raw_id, url=url, name=name, category=cat))
            except Exception as e:
                print(f"[UYARI] lists.json okunurken hata oluştu: {e}")

        # 2. Ortam Değişkeni Kontrolü
        env_lists = os.environ.get("TWITTER_LISTS") or os.environ.get("TWITTER_LIST_URLS")
        if env_lists and not lists:
            env_lists = env_lists.strip()
            # JSON formatında mı?
            if env_lists.startswith("[") and env_lists.endswith("]"):
                try:
                    data = json.loads(env_lists)
                    for item in data:
                        if isinstance(item, dict):
                            raw_id = extract_list_id(item.get("url") or item.get("id") or item.get("list_id", ""))
                            if raw_id:
                                name = item.get("name", "")
                                cat = item.get("category", "") or slugify(name)
                                url = item.get("url") or f"https://x.com/i/lists/{raw_id}"
                                lists.append(TwitterListConfig(list_id=raw_id, url=url, name=name, category=cat))
                        elif isinstance(item, str):
                            raw_id = extract_list_id(item)
                            if raw_id:
                                lists.append(TwitterListConfig(list_id=raw_id, url=f"https://x.com/i/lists/{raw_id}"))
                except Exception as e:
                    print(f"[UYARI] Ortam değişkenindeki JSON listesi çözümlenemedi: {e}")

            # Düz metin / virgülle ayrılmış mı?
            if not lists:
                tokens = re.split(r'[\r\n,]+', env_lists)
                for token in tokens:
                    token = token.strip()
                    if not token:
                        continue
                    name = ""
                    cat = ""
                    if "|" in token:
                        parts = token.split("|", 1)
                        token_url = parts[0].strip()
                        name = parts[1].strip()
                        cat = slugify(name)
                    else:
                        token_url = token

                    raw_id = extract_list_id(token_url)
                    if raw_id:
                        url = token_url if token_url.startswith("http") else f"https://x.com/i/lists/{raw_id}"
                        lists.append(TwitterListConfig(list_id=raw_id, url=url, name=name, category=cat))

        # 3. Varsayılan liste fallback
        if not lists:
            lists.append(
                TwitterListConfig(
                    list_id=cls.DEFAULT_LIST_ID,
                    url=f"https://x.com/i/lists/{cls.DEFAULT_LIST_ID}",
                    name=cls.DEFAULT_LIST_NAME,
                    category="gundem"
                )
            )

        # Tekrarlayan list_id'leri filtrele
        unique_lists = []
        seen_ids = set()
        for item in lists:
            if item.list_id not in seen_ids:
                seen_ids.add(item.list_id)
                unique_lists.append(item)

        return unique_lists
