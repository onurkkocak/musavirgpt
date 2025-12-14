import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import re

# --- AYARLAR ---
BASE_URL = "https://www.mevzuat.gov.tr/" 
KLASOR_ADI = "mevzuat_arsivi_tam"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def isim_temizle(baslik):
    temiz = re.sub(r'[\\/*?:"<>|]', "", baslik).strip()
    return temiz[:150]

def cekirdek_robotu_baslat():
    print("🤖 Mevzuat Robotu Devrede (Görsel Tıklama Modu)")
    
    if not os.path.exists(KLASOR_ADI):
        os.makedirs(KLASOR_ADI)

    # 1. Chrome Ayarları
    chrome_options = Options()
    # chrome_options.add_argument("--headless") # Görünür çalışsın
    chrome_options.add_argument("window-size=1200,800")

    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    except Exception as e:
        print(f"\n❌ SÜRÜCÜ HATASI: {e}. Lütfen Selenium ve Chrome'un güncel olduğundan emin olun.")
        return

    toplam_link_sayisi = 0
    
    # Hedefleyeceğimiz Kategori İsimleri (Resimdeki Kutucuklar)
    kategoriler = ["Kanunlar", "Tebliğler"]

    for kategori in kategoriler:
        print(f"\n---> {kategori} Kategorisi Çekiliyor...")
        driver.get(BASE_URL)
        
        try:
            # 2. Kategoriyi Bul ve Tıkla (Resimdeki kutucuklar)
            kategori_linki = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, f"//div[contains(text(), '{kategori}')]"))
            )
            kategori_linki.click()
            time.sleep(2) # Sayfanın yüklenmesini bekle

            # 3. Linkleri Topla (Artık listedeyiz)
            # Mevzuat listeleri genellikle 'Mevzuat Detay' linklerini içerir
            detay_linkleri = set()
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, 'a'))
            )
            
            link_etiketleri = driver.find_elements(By.TAG_NAME, 'a')
            
            for tag in link_etiketleri:
                href = tag.get_attribute('href')
                # Mevzuat detay linklerini filtrele (Örn: /MevzuatDetay.aspx?...)
                if href and 'MevzuatDetay.aspx?' in href:
                    detay_linkleri.add(href)
            
            url_listesi = list(detay_linkleri)
            print(f"🎯 Kategori {kategori} için {len(url_listesi)} adet detay linki bulundu.")
            toplam_link_sayisi += len(url_listesi)

            # 4. Detay Sayfalarını Çek ve Kaydet (Çekirdek Scraping)
            for i, url in enumerate(url_listesi):
                print(f"⬇️ [{i+1}/{len(url_listesi)}] Çekiliyor...")
                
                try:
                    driver.get(url)
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
                    
                    # Başlık ve İçerik Bulma
                    baslik_tag = driver.find_element(By.TAG_NAME, 'h1')
                    baslik_text = baslik_tag.text.strip() if baslik_tag else f"{kategori}_Belgesi_{i+1}"
                    
                    # İçeriğin tamamını al
                    icerik_alani = driver.find_element(By.TAG_NAME, 'body')
                    ham_metin = icerik_alani.text
                    
                    # Metni Temizle (Gereksiz kısa satırları atar)
                    temiz_metin = "\n".join([s.strip() for s in ham_metin.splitlines() if len(s.strip()) > 50])

                    # Kaydet
                    dosya_adi = isim_temizle(baslik_text)
                    dosya_yolu = os.path.join(KLASOR_ADI, f"{dosya_adi}.txt")

                    with open(dosya_yolu, "w", encoding="utf-8") as f:
                        f.write(f"KAYNAK: {url}\nBAŞLIK: {baslik_text}\n\n{temiz_metin}")

                except Exception as e:
                    print(f"   ⚠️ Hata: {url} çekilemedi -> {e}")

        except Exception as e:
            print(f"❌ HATA: {kategori} kategorisine tıklama veya listeleme başarısız oldu: {e}")
            
    driver.quit()
    print(f"\n✅ VERİ TAMAMLAMA BAŞARILI: Toplam {toplam_link_sayisi} adet link taranıp kaydedildi.")

if __name__ == "__main__":
    cekirdek_robotu_baslat()