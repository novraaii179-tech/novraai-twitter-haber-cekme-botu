import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import firebase_admin
from firebase_admin import credentials, firestore
from config import Config


class Database:
    """Firebase Firestore Veritabanı Yöneticisi"""

    def __init__(self):
        self.db = self._init_firebase()

    def _init_firebase(self):
        """Firebase Admin SDK'yı başlatır."""
        print("-> Firebase Firestore bağlantısı kuruluyor...")
        try:
            cred_dict = Config.get_firebase_credentials()
            cred = credentials.Certificate(cred_dict)

            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred)

            client = firestore.client()
            print("-> Firebase bağlantısı başarılı.")
            return client
        except Exception as e:
            sys.exit(f"KRİTİK HATA: Firebase başlatılamadı: {e}")

    def save_news(self, news_doc: Dict[str, Any]) -> Tuple_Result:
        """
        Haberi Firestore'a kaydeder.
        Config.SAVE_MODE değerine göre:
        - 'both': Hem ana koleksiyona ('haberler') hem de kategori koleksiyonuna ('haberler_{kategori}')
        - 'single': Yalnızca ana koleksiyona ('haberler')
        - 'categorized': Yalnızca kategori koleksiyonuna
        """
        tweet_id = news_doc["tweet_id"]
        category = news_doc.get("category", "gundem")
        
        # Firestore sunucu zaman damgası ekle
        data_to_save = dict(news_doc)
        data_to_save["updated_at"] = firestore.SERVER_TIMESTAMP

        target_collections = []
        if Config.SAVE_MODE in ["both", "single"]:
            target_collections.append(Config.MAIN_COLLECTION)
        if Config.SAVE_MODE in ["both", "categorized"]:
            cat_collection = f"{Config.MAIN_COLLECTION}_{category}"
            target_collections.append(cat_collection)

        is_new = False
        try:
            for coll_name in target_collections:
                doc_ref = self.db.collection(coll_name).document(tweet_id)
                existing = doc_ref.get()
                if existing.exists:
                    doc_ref.set(data_to_save, merge=True)
                else:
                    doc_ref.set(data_to_save)
                    is_new = True

            # Kategori Fihristini Güncelle (Uygulama ve Web için dinamik kategori menüsü)
            self._update_category_meta(category, news_doc.get("category_name", category))

            return is_new, True
        except Exception as e:
            print(f"[HATA] Firestore kayıt hatası ({tweet_id}): {e}")
            return False, False

    def _update_category_meta(self, category_slug: str, category_name: str):
        """Web ve mobil uygulamanın dinamik kategorileri çekebilmesi için 'kategoriler' koleksiyonunu günceller."""
        try:
            cat_ref = self.db.collection("kategoriler").document(category_slug)
            cat_ref.set({
                "slug": category_slug,
                "name": category_name,
                "collection_name": f"{Config.MAIN_COLLECTION}_{category_slug}",
                "last_news_at": firestore.SERVER_TIMESTAMP
            }, merge=True)
        except Exception:
            pass

    def delete_expired_news(self, retention_days: int = 2) -> int:
        """
        2 günden (veya belirtilen retention_days) eski haberleri Firestore'dan otomatik siler.
        Hem ana koleksiyonu hem de kategori koleksiyonlarını tarar.
        """
        now = datetime.now(timezone.utc)
        cutoff_dt = now - timedelta(days=retention_days)
        cutoff_ts = int(cutoff_dt.timestamp())
        cutoff_iso = cutoff_dt.isoformat()

        print(f"\n-> [OTOMATİK TEMİZLEME] {retention_days} günden eski ({cutoff_dt.strftime('%d.%m.%Y %H:%M')} UTC öncesi) haberler aranıyor...")

        # Temizlenecek koleksiyonları belirle
        collections_to_check = [Config.MAIN_COLLECTION]
        
        # Dinamik kategorileri çek
        try:
            cats = self.db.collection("kategoriler").stream()
            for c in cats:
                cat_data = c.to_dict()
                coll_name = cat_data.get("collection_name")
                if coll_name and coll_name not in collections_to_check:
                    collections_to_check.append(coll_name)
        except Exception as e:
            print(f"[UYARI] Kategoriler listelenirken hata: {e}")

        total_deleted = 0

        for coll_name in collections_to_check:
            try:
                coll_ref = self.db.collection(coll_name)
                
                # 1. expires_timestamp veya published_timestamp ile ara
                query = coll_ref.where("published_timestamp", "<=", cutoff_ts).limit(450)
                docs = list(query.stream())

                # Eğer published_timestamp bulunamadıysa (eski kayıtlar için created_at kontrolü)
                if not docs:
                    # Alternatif olarak expires_at kontrolü
                    query2 = coll_ref.where("expires_at", "<=", now.isoformat()).limit(450)
                    docs = list(query2.stream())

                if docs:
                    batch = self.db.batch()
                    deleted_in_batch = 0
                    for doc in docs:
                        batch.delete(doc.reference)
                        deleted_in_batch += 1

                    batch.commit()
                    total_deleted += deleted_in_batch
                    print(f"   ✓ '{coll_name}' koleksiyonundan {deleted_in_batch} eski haber silindi.")
            except Exception as e:
                # İndeks hatası veya koleksiyon yoksa sessizce geç
                if "requires an index" in str(e):
                    # İndeks gerekmeden client-side tarih kontrolü ile silme (fallback)
                    fallback_deleted = self._fallback_cleanup_by_date(coll_name, cutoff_ts)
                    total_deleted += fallback_deleted
                else:
                    print(f"   [!] '{coll_name}' temizlenirken uyarı: {e}")

        if total_deleted > 0:
            print(f"-> [TEMİZLEME TAMAMLANDI] Toplam {total_deleted} eski haber veritabanından başarıyla temizlendi.\n")
        else:
            print("-> [TEMİZLEME TAMAMLANDI] Silinecek süresi geçmiş eski haber bulunamadı.\n")

        return total_deleted

    def _fallback_cleanup_by_date(self, coll_name: str, cutoff_ts: int) -> int:
        """İndeks gerekmeden dökümanları inceleyip 2 günden eskileri siler."""
        deleted = 0
        try:
            docs = self.db.collection(coll_name).limit(200).stream()
            batch = self.db.batch()
            for doc in docs:
                data = doc.to_dict()
                doc_ts = data.get("published_timestamp") or data.get("expires_timestamp")
                if doc_ts and doc_ts <= cutoff_ts:
                    batch.delete(doc.reference)
                    deleted += 1
            if deleted > 0:
                batch.commit()
                print(f"   ✓ [Fallback] '{coll_name}' koleksiyonundan {deleted} eski haber temizlendi.")
        except Exception:
            pass
        return deleted


Tuple_Result = Any
