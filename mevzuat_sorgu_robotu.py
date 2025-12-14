import requests
from bs4 import BeautifulSoup
import time
import os
import re

# --- AYARLAR ---
# Türkiye'deki en önemli Vergi Kanunlarının numaraları
KANUN_NUMARALARI = ["193", "5520", "213", "3065", "4769", "5811"] 
KLASOR_ADI = "mevzuat_arsivi_v2"
# Mevzuat.gov.tr'deki arama sayfasının adresi veya listeleme adresi
BASE_URL = "https://www.mevzuat.gov.tr" 
SEARCH_URL_TEMPLATE = "https://www.mevzuat.gov.tr/MevzuatListe.aspx?KanunNo={kanun_no}" 

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
MIN_BEKLEME = 1.5 

def isim_temizle(baslik):
    """Dosya adında olmaması gerekenleri temizler."""
    temiz = re.sub(r'[\\/*?:"<>|]', "", baslik).strip()
    return temiz[:150]

def cekirdek_sorgu_robotu():
    print("🤖 Mevzuat Sorgu Robotu Devrede (Kanun Numarasına Göre)")
    
    if not os.path.exists(KLASOR_ADI):
        os.makedirs(KLASOR_ADI)

    toplam_link_sayisi = 0
    
    for kanun_no in KANUN_NUMARALARI:
        sorgu_url = SEARCH_URL_TEMPLATE.format(kanun_no=kanun_no)
        print(f"\n1. Adım: Kanun No {kanun_no} için sorgu çekiliyor: {sorgu_url}")
        
        try:
            # 1. Sorgu Sonuç Sayfasını Çek
            response = requests.get(sorgu_url, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # 2. Linkleri Bul (Sonuç Tablosu İçinden)
            # Mevzuat siteleri sonuçları genellikle bir tablo (table) içinde tutar.
            detay_linkleri = set()
            
            # 'Mevzuat Detay' veya benzeri linkleri içeren tabloları hedefle
            tablo_govdesi = soup.find('div', id="ana_metin_bolumu") # Bu ID'yi değiştirmek gerekebilir.
            if not tablo_govdesi: tablo_govdesi = soup.find('body')

            # Tüm linkleri çek (Mevzuat.gov.tr'de linkler genellikle bu formatta)
            link_etiketleri = tablo_govdesi.find_all('a', href=True)
            
            for tag in link_etiketleri:
                href = tag.get('href')
                # Mevzuat detay linklerini filtrele (Örn: /MevzuatDetay.aspx?...)
                if 'MevzuatDetay.aspx?' in href:
                    tam_url = href if href.startswith('http') else BASE_URL + href
                    detay_linkleri.add(tam_url)
            
            url_listesi = list(detay_linkleri)
            print(f"🎯 Kanun No {kanun_no} için {len(url_listesi)} adet detay linki bulundu.")
            toplam_link_sayisi += len(url_listesi)

            # 3. Detay Sayfalarını Tek Tek Çek ve Kaydet
            for i, url in enumerate(url_listesi):
                bekleme_suresi = random.uniform(MIN_BEKLEME, 3) 
                # print(f"⬇️ [{i+1}/{len(url_listesi)}] Çekiliyor... (Bekle: {bekleme_suresi:.2f}s)")
                
                # İçerik çekme mantığı (Mevzuat.gov.tr'de basittir)
                try:
                    resp = requests.get(url, headers=HEADERS, timeout=20)
                    detay_soup = BeautifulSoup(resp.content, 'html.parser')

                    # Başlık ve İçerik Bulma
                    baslik_tag = detay_soup.find('h1')
                    baslik_text = baslik_tag.get_text().strip() if baslik_tag else f"Mevzuat_{kanun_no}_Belgesi_{i+1}"
                    
                    icerik_alani = detay_soup.find('div', class_="MuiBox-root") # Olası içerik div'i
                    if not icerik_alani: icerik_alani = detay_soup.find('body')

                    ham_metin = icerik_alani.get_text(separator="\n")
                    temiz_metin = "\n".join([s.strip() for s in ham_metin.splitlines() if len(s.strip()) > 50])

                    # Kaydet
                    dosya_adi = isim_temizle(baslik_text)
                    dosya_yolu = os.path.join(KLASOR_ADI, f"{dosya_adi}.txt")

                    with open(dosya_yolu, "w", encoding="utf-8") as f:
                        f.write(f"KAYNAK: {url}\nBAŞLIK: {baslik_text}\n\n{temiz_metin}")

                    # time.sleep(bekleme_suresi) # Hızlıca çeksin diye yorum satırı yapıldı
                
                except Exception as e:
                    print(f"   ⚠️ Hata: {url} çekilemedi -> {e}")

        except Exception as e:
            print(f"❌ HATA: Kanun No {kanun_no} sonuç sayfası çekilemedi: {e}")
            
    print(f"\n✅ VERİ TAMAMLAMA BAŞARILI: Toplam {toplam_link_sayisi} adet mevzuat belgesi çekildi.")

if __name__ == "__main__":
    import random
    cekirdek_sorgu_robotu()