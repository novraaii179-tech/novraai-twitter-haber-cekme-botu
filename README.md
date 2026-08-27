# Twitter'dan Firebase Firestore'a Otomatik Haber Botu

Bu bot, X (Twitter) üzerindeki listedeki (Liste ID: `1975820683461460354`) haber paylaşımlarını, görselleri ve videoları (en yüksek çözünürlüklü MP4 linkleri) toplayarak Firebase Firestore veritabanına otomatik olarak kaydeder.

---

## 📁 Proje Dosya Yapısı

```
├── .github/
│   └── workflows/
│       └── otomasyon.yml    # GitHub Actions otomatik çalışma ayarı (30 dk bir)
├── bot.py                   # Haberleri, fotoğrafları ve videoları çeken ana kod
├── requirements.txt         # Gerekli Python kütüphaneleri
└── README.md                # Kurulum ve kullanım rehberi
```

---

## 🚀 Adım Adım Kurulum Kılavuzu

### 1. Adım: Firebase Servis Hesabı Dosyasını Alma
1. [Firebase Console](https://console.firebase.google.com/) adresine gidin ve projenizi açın.
2. Sol üstteki **Proje Ayarları (Dişli simgesi) > Hizmet Hesapları (Service Accounts)** sekmesine geçin.
3. **Yeni Özel Anahtar Oluştur (Generate new private key)** butonuna tıklayın.
4. Bilgisayarınıza inen `.json` dosyasını Not Defteri ile açın ve içindeki tüm metni kopyalayın.

### 2. Adım: Twitter / X Çerezlerini (Cookies) Alma
1. Tarayıcınıza (Chrome veya Edge) **Cookie-Editor** eklentisini kurun.
2. [x.com](https://x.com) adresine girip hesabınızla oturum açın.
3. Cookie-Editor eklentisine tıklayın, alttaki **Export > Export as JSON** seçeneğine basın (çerezler panoya kopyalanır).

### 3. Adım: GitHub Deposu Açma ve Dosyaları Yükleme
1. [GitHub](https://github.com/) üzerinde yeni bir **Private (Gizli)** depo (repository) açın.
2. Bu ZIP dosyasının içindeki tüm dosyaları (`bot.py`, `requirements.txt` ve `.github` klasörünü) deponuza yükleyin.

### 4. Adım: Şifreleri (Secrets) GitHub'a Ekleme
1. GitHub deponuzda **Settings > Secrets and variables > Actions** sayfasına gidin.
2. **New repository secret** butonuna tıklayarak şu 2 değişkeni oluşturun:
   - `FIREBASE_CREDENTIALS`: 1. adımda kopyaladığınız Firebase JSON içeriği.
   - `TWITTER_COOKIES`: 2. adımda kopyaladığınız X çerez metni.

### 5. Adım: Test Etme ve Çalıştırma
1. Deponuzun **Actions** sekmesine gidin.
2. Sol taraftan **Twitter Firestore Haber Botu** iş akışını seçin.
3. **Run workflow** butonuna basarak ilk çalıştırmayı yapın.
4. Firebase Firestore konsolunda `haberler` koleksiyonunun oluştuğunu ve tweetlerin görselleri, videoları ve metinleriyle eklendiğini göreceksiniz.
