import os
import requests
from bs4 import BeautifulSoup
import time
import re

# --- AYARLAR ---
# Senin indirdiğin dosyanın adı
YEREL_DOSYA = "liste.html"
KLASOR_ADI = "tebligler_txt_arsivi"
BASE_URL = "https://www.gib.gov.tr"

# Kendimizi Chrome gibi göstermeye devam edelim (Detay sayfaları için)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def isim_temizle(baslik):
    return re.sub(r'[\\/*?:"<>|]', "", baslik)[:150].strip()

def yerel_listeyi_islee():
    print(f"📂 Yerel dosya okunuyor: {YEREL_DOSYA}")
    
    if not os.path.exists(YEREL_DOSYA):
        print("❌ HATA: 'liste.html' bulunamadı! Lütfen GİB sayfasını farklı kaydet ile bu isimle klasöre atın.")
        return

    if not os.path.exists(KLASOR_ADI):
        os.makedirs(KLASOR_ADI)

    # 1. Yerel HTML'i Oku
    with open(YEREL_DOSYA, "r", encoding="utf-8") as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")
    
    # 2. Linkleri Ayıkla
    # Yerel dosyada artık engel yok, her şeyi görebiliriz.
    tum_linkler = soup.find_all("a", href=True)
    
    hedef_linkler = []
    print(f"🔎 Sayfadaki toplam link: {len(tum_linkler)}. Mevzuat linkleri aranıyor...")

    for link in tum_linkler:
        href = link['href']
        metin = link.text.strip()
        
        # Filtre: İçinde 'mevzuat' geçen veya mantıklı uzunlukta olan linkleri al
        # GİB linkleri genelde /mevzuat/ veya /node/ ile başlar
        if len(metin) > 10 and (href.startswith("/") or "gib.gov.tr" in href):
            tam_url = href if href.startswith("http") else BASE_URL + href
            
            # Mükerrer Ekleme
            if tam_url not in [x['url'] for x in hedef_linkler]:
                hedef_linkler.append({"url": tam_url, "baslik": metin})

    print(f"🎯 İŞLENECEK TEBLİĞ SAYISI: {len(hedef_linkler)}")
    
    # 3. Listeyi Bulduk, Şimdi Tek Tek İndirelim
    basarili = 0
    print("🚀 İndirme işlemi başlıyor...")

    for i, item in enumerate(hedef_linkler):
        url = item['url']
        baslik = isim_temizle(item['baslik'])
        dosya_yolu = os.path.join(KLASOR_ADI, f"{baslik}.txt")

        # Dosya varsa atla
        if os.path.exists(dosya_yolu):
            print(f"⏩ Zaten var ({i+1}): {baslik[:30]}...")
            basarili += 1
            continue

        print(f"⬇️ [{i+1}/{len(hedef_linkler)}] İndiriliyor: {baslik[:40]}...")

        try:
            # Detay sayfasına istek atıyoruz
            detay_resp = requests.get(url, headers=HEADERS, timeout=15)
            
            if detay_resp.status_code == 200:
                detay_soup = BeautifulSoup(detay_resp.content, "html.parser")
                
                # İçeriği bul
                icerik_alani = detay_soup.find("div", class_="content")
                if not icerik_alani:
                    icerik_alani = detay_soup.find("div", id="content") # Alternatif ID
                
                ham_metin = icerik_alani.get_text(separator="\n") if icerik_alani else detay_soup.get_text(separator="\n")
                
                # Temizle
                temiz_metin = "\n".join([satir.strip() for satir in ham_metin.splitlines() if len(satir.strip()) > 2])

                # Kaydet
                with open(dosya_yolu, "w", encoding="utf-8") as f:
                    f.write(f"KAYNAK: {url}\nBASLIK: {item['baslik']}\n\n{temiz_metin}")
                
                basarili += 1
                time.sleep(0.3) # Kibar olalım
            else:
                print(f"   ❌ Sayfa açılamadı: {detay_resp.status_code}")

        except Exception as e:
            print(f"   ⚠️ Hata: {e}")

    print(f"\n✅ OPERASYON TAMAMLANDI! {basarili} dosya '{KLASOR_ADI}' içine kaydedildi.")

if __name__ == "__main__":
    yerel_listeyi_islee()