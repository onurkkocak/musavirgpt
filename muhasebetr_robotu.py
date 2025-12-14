import requests
from bs4 import BeautifulSoup
import time
import os
import re
import random

# --- AYARLAR ---
BASE_URL = "https://www.muhasebetr.com"
LISTE_URL = "https://www.muhasebetr.com/guncelmevzuat/" 
KLASOR_ADI = "muhasebetr_arsivi"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
MIN_BEKLEME = 1  # Her sayfa arası minimum bekleme (Güvenlik)

def isim_temizle(baslik):
    """Dosya adında olmaması gerekenleri temizler."""
    temiz = re.sub(r'[\\/*?:"<>|]', "", baslik).strip()
    return temiz[:150]

def cekirdek_muhasebetr_robotu():
    print("🤖 Muhasebetr Robotu Devrede (Stabil Çekim)")
    
    if not os.path.exists(KLASOR_ADI):
        os.makedirs(KLASOR_ADI)

    # 1. Liste Sayfasını Çek
    print(f"1. Adım: Liste çekiliyor: {LISTE_URL}")
    try:
        response = requests.get(LISTE_URL, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
    except Exception as e:
        print(f"❌ HATA: Liste sayfası çekilemedi. Bağlantı hatası: {e}")
        return

    # 2. Detay Linklerini Bul
    print("2. Adım: Detay linkleri taranıyor...")
    detay_linkleri = set()
    
    # Muhasebetr linkleri genellikle /guncelmevzuat/ altında bir tebliğe işaret eder.
    link_etiketleri = soup.find_all('a', href=True)
    
    for tag in link_etiketleri:
        href = tag.get('href')
        # Sadece güncel mevzuat detay linklerini filtrele
        if '/guncelmevzuat/' in href and len(href.split('/')) > 3: 
            tam_url = href if href.startswith('http') else BASE_URL + href
            detay_linkleri.add(tam_url)
    
    url_listesi = list(detay_linkleri)
    print(f"🎯 Toplam {len(url_listesi)} adet detay linki bulundu.")
    toplam_cekilen = 0

    # 3. Detay Sayfalarını Tek Tek Çek ve Kaydet
    for i, url in enumerate(url_listesi):
        bekleme_suresi = random.uniform(MIN_BEKLEME, 3) 
        print(f"⬇️ [{i+1}/{len(url_listesi)}] Çekiliyor... (Bekle: {bekleme_suresi:.2f}s)")
        
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            detay_soup = BeautifulSoup(resp.content, 'html.parser')

            # Başlık Bulma (H1 veya ana başlık)
            baslik_tag = detay_soup.find('h1')
            baslik_text = baslik_tag.get_text().strip() if baslik_tag else f"MTR_Belgesi_{i+1}"
            
            # Ana İçerik Bloğunu Bulma (Genellikle bir div veya article içindedir)
            # Bu, en kritik adımdır, içeriği tutan ana elementi hedefle
            icerik_alani = detay_soup.find('article') 
            if not icerik_alani: icerik_alani = detay_soup.find('div', id="ana_icerik") 
            if not icerik_alani: icerik_alani = detay_soup.find('body') # Son çare

            # Metni temizle
            ham_metin = icerik_alani.get_text(separator="\n")
            temiz_metin = "\n".join([s.strip() for s in ham_metin.splitlines() if len(s.strip()) > 50])

            # Kaydet
            dosya_adi = isim_temizle(baslik_text)
            dosya_yolu = os.path.join(KLASOR_ADI, f"{dosya_adi}.txt")

            with open(dosya_yolu, "w", encoding="utf-8") as f:
                f.write(f"KAYNAK: {url}\nBAŞLIK: {baslik_text}\n\n{temiz_metin}")

            toplam_cekilen += 1
            time.sleep(bekleme_suresi)

        except Exception as e:
            print(f"   ⚠️ Hata: {url} çekilemedi -> {e}")

    print(f"\n✅ VERİ TAMAMLAMA BAŞARILI: Toplam {toplam_cekilen} adet mevzuat belgesi çekildi.")

if __name__ == "__main__":
    cekirdek_muhasebetr_robotu()