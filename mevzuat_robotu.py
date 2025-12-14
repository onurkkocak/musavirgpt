import requests
from bs4 import BeautifulSoup
import time
import os
import re

# --- AYARLAR ---
# Örneğin, 193 Sayılı Gelir Vergisi Kanunu'nu çekeceğimiz varsayımıyla:
BASE_URL = "https://www.mevzuat.gov.tr" 
LISTE_URL = "https://www.mevzuat.gov.tr/mevzuat/kanun/433.html" # GVK'nın listelendiği sayfa örneği
KLASOR_ADI = "mevzuat_arsivi"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
MIN_BEKLEME = 1  # Her sayfa arası minimum bekleme (Ban riskini azaltır)

def isim_temizle(baslik):
    """Dosya adında olmaması gerekenleri temizler."""
    temiz = re.sub(r'[\\/*?:"<>|]', "", baslik).strip()
    return temiz[:150]

def cekirdek_robotu_baslat():
    print("🤖 Mevzuat Robotu Devrede (Stabil Çekim)")
    
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
    # Mevzuat siteleri genellikle linkleri 'a' etiketleri veya tablolar içinde tutar.
    # Örn: 'kanun/433/teblig/1' gibi göreceli linkleri arayalım
    link_etiketleri = soup.find_all('a', href=True)
    detay_linkleri = set()
    
    for tag in link_etiketleri:
        href = tag.get('href')
        # Sadece göreceli linkleri veya tam mevzuat linklerini al
        if ('/kanun/' in href or '/yonetmelik/' in href) and href.endswith('.html'):
            tam_url = href if href.startswith('http') else BASE_URL + href
            detay_linkleri.add(tam_url)
    
    url_listesi = list(detay_linkleri)
    print(f"🎯 Toplam {len(url_listesi)} adet detay linki bulundu.")

    # 3. Detay Sayfalarını Tek Tek Çek ve Kaydet
    basarili = 0
    for i, url in enumerate(url_listesi):
        bekleme_suresi = random.uniform(MIN_BEKLEME, 3) # Ban riskini azaltmak için yavaş çalış
        print(f"⬇️ [{i+1}/{len(url_listesi)}] Çekiliyor... (Bekle: {bekleme_suresi:.2f}s)")
        
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            detay_soup = BeautifulSoup(resp.content, 'html.parser')

            # Başlık ve İçerik Bulma (Mevzuat.gov.tr'de genellikle basittir)
            baslik_tag = detay_soup.find('h1')
            baslik_text = baslik_tag.get_text().strip() if baslik_tag else f"Mevzuat_Belgesi_{i+1}"
            
            # Ana içerik bloğunu bulma (id="mainContent" veya benzeri)
            icerik_alani = detay_soup.find('div', id="ana_metin_bolumu") 
            if not icerik_alani:
                 # Genellikle sayfanın tamamı içeriği içerir
                 icerik_alani = detay_soup.find('body')

            # Metni temizle
            ham_metin = icerik_alani.get_text(separator="\n")
            temiz_metin = "\n".join([s.strip() for s in ham_metin.splitlines() if len(s.strip()) > 50])

            # Kaydet
            dosya_adi = isim_temizle(baslik_text)
            dosya_yolu = os.path.join(KLASOR_ADI, f"{dosya_adi}.txt")

            with open(dosya_yolu, "w", encoding="utf-8") as f:
                f.write(f"KAYNAK: {url}\nBAŞLIK: {baslik_text}\n\n{temiz_metin}")

            basarili += 1
            time.sleep(bekleme_suresi)

        except Exception as e:
            print(f"   ⚠️ Hata: {url} çekilemedi -> {e}")

    print(f"\n✅ VERİ TAMAMLAMA BAŞARILI: {basarili} dosya '{KLASOR_ADI}' klasörüne eklendi.")

if __name__ == "__main__":
    import random
    cekirdek_robotu_baslat()