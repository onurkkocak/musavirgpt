import requests
from bs4 import BeautifulSoup
import json
import time

# --- AYARLAR ---
# Senin verdiğin tam adres
TARGET_URL = "https://www.turmob.org.tr/sirkuler/1/vergi"
BASE_URL = "https://www.turmob.org.tr"
OUTPUT_FILE = "musavirgpt_veri_seti.json"

def verileri_cek():
    print(f"🌍 TÜRMOB Vergi Sirküleri taranıyor: {TARGET_URL}...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    }

    try:
        # 1. Ana Listeyi Çek
        # verify=False yapıyoruz çünkü bazen devlet sitelerinin SSL sertifikaları Python'da hata verebiliyor.
        response = requests.get(TARGET_URL, headers=headers, verify=False) 
        
        if response.status_code != 200:
            print(f"❌ Siteye erişilemedi! Hata Kodu: {response.status_code}")
            return

        soup = BeautifulSoup(response.content, "html.parser")
        
        # Linkleri Bulma Stratejisi:
        # Sayfadaki tüm <a> etiketlerini al, içinde 'sirkuler' geçenleri ayıkla.
        veriler = []
        bulunan_linkler = []
        
        tum_linkler = soup.find_all("a", href=True)
        
        for link in tum_linkler:
            href = link['href']
            # Link filtreleme: Sadece detay sayfalarına gidenleri alalım
            # Genellikle '/sirkuler/' veya sayısal ID içerirler.
            if "/sirkuler/" in href and len(href) > 25: 
                full_url = BASE_URL + href if href.startswith("/") else href
                
                # Mükerrerleri ve ana sayfa linkini ele
                if full_url not in bulunan_linkler and full_url != TARGET_URL:
                    bulunan_linkler.append(full_url)

        print(f"✅ Toplam {len(bulunan_linkler)} adet sirküler linki bulundu. Detaylar çekiliyor...")

        # İlk 10 tanesini çekelim (Deneme amaçlı, sonra artırabilirsin)
        for i, url in enumerate(bulunan_linkler[:10]):
            try:
                print(f"   ⏳ İndiriliyor ({i+1}): {url}")
                detay_resp = requests.get(url, headers=headers, verify=False)
                detay_soup = BeautifulSoup(detay_resp.content, "html.parser")

                # --- BAŞLIK BULMA ---
                # Görselde başlık mavi bantın içinde görünüyor, muhtemelen h1 veya h2
                baslik = "Başlık Yok"
                header_tag = detay_soup.find("h1") or detay_soup.find("h2") or detay_soup.find("h3")
                if header_tag:
                    baslik = header_tag.get_text(strip=True)

                # --- İÇERİK (ÖZET) BULMA ---
                # Senin 2. görseldeki "ÖZET" kutusunu hedefliyoruz.
                icerik_metni = ""
                
                # 1. Yöntem: 'ÖZET' kelimesini içeren bir başlık var mı?
                # Genellikle <div class="ozet"> veya <strong>ÖZET</strong> gibi olur.
                content_div = detay_soup.find("div", class_="news-detail") or detay_soup.find("div", {"id": "page-content"})
                
                if content_div:
                    icerik_metni = content_div.get_text(separator=" ", strip=True)
                else:
                    # Bulamazsa tüm paragrafları al
                    texts = [p.get_text(strip=True) for p in detay_soup.find_all("p")]
                    icerik_metni = " ".join(texts)

                # Temizlik ve Kontrol
                icerik_metni = icerik_metni.replace("\n", " ").replace("\r", "")
                
                if len(icerik_metni) > 50: # Sadece dolu olanları kaydet
                    veriler.append({
                        "baslik": baslik,
                        "icerik": icerik_metni,
                        "kaynak": "TÜRMOB Sirküleri",
                        "url": url
                    })
                
                time.sleep(0.5) # Kibar olalım, siteyi yormayalım

            except Exception as e:
                print(f"   ⚠️ Bu linkte hata oldu: {e}")

        # Kaydet
        if len(veriler) > 0:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(veriler, f, ensure_ascii=False, indent=4)
            print(f"🎉 SÜPER! Toplam {len(veriler)} adet sirküler '{OUTPUT_FILE}' dosyasına kaydedildi.")
        else:
            print("⚠️ Hiç veri kaydedilemedi. Site yapısı değişmiş olabilir veya JavaScript engeli var.")

    except Exception as e:
        print(f"❌ Kritik Hata: {e}")

if __name__ == "__main__":
    # SSL Uyarılarını gizle (görüntü kirliliği yapmasın)
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    verileri_cek()