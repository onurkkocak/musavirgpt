from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import json
import time
import requests
import io
import pdfplumber
import os

# --- AYARLAR ---
BASE_URL = "https://www.turmob.org.tr"
START_URL = "https://www.turmob.org.tr/ekutuphane/e2f9f8fd-af81-456b-8626-2e938f66dd45/mevzuat-sirkuleri/1"
OUTPUT_FILE = "turmob_kutuphane_veri_seti.json"
TARANACAK_YIL_ADEDI = 2 # Kaç yıllık veri çekilsin

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def tabloyu_markdown_yap(page):
    """Tabloları metne çevirir"""
    markdown_text = ""
    settings = {"vertical_strategy": "lines", "horizontal_strategy": "lines", "intersection_x_tolerance": 5}
    tables = page.extract_tables(table_settings=settings)
    if not tables:
        settings["vertical_strategy"] = "text"
        settings["horizontal_strategy"] = "text"
        tables = page.extract_tables(table_settings=settings)

    for table in tables:
        if not table: continue
        clean_table = [[str(c).replace('\n', ' ').strip() if c else " " for c in row] for row in table]
        if not clean_table: continue
        try:
            markdown_text += "\n\n| " + " | ".join(clean_table[0]) + " |\n"
            markdown_text += "| " + " | ".join(["---"] * len(clean_table[0])) + " |\n"
            for row in clean_table[1:]:
                markdown_text += "| " + " | ".join(row) + " |\n"
            markdown_text += "\n"
        except: continue
    return markdown_text

def get_full_url(href):
    """Göreceli linkleri tam linke çevirir"""
    if not href: return None
    if href.startswith("http"): return href
    if href.startswith("/"): return BASE_URL + href
    return BASE_URL + "/" + href

def process_sirkuler_page(driver, sirkuler_url):
    """Sirküler detay sayfasını işler"""
    try:
        driver.get(sirkuler_url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(1) # Sayfa yüklenme payı
        
        data = {
            "baslik": driver.title,
            "icerik": "",
            "pdf_url": "BULUNAMADI",
            "url": sirkuler_url,
            "kaynak": "TÜRMOB"
        }

        # Başlığı H1'den almaya çalış
        try:
            h1 = driver.find_element(By.TAG_NAME, "h1").text.strip()
            if h1: data["baslik"] = h1
        except: pass

        # PDF Linkini Bul
        try:
            # Genellikle "PDF Görüntüle" veya ikonlu buton
            pdf_links = driver.find_elements(By.XPATH, "//a[contains(@href, '.pdf') or contains(text(), 'PDF') or contains(@class, 'btn')]")
            target_pdf = None
            for pl in pdf_links:
                href = pl.get_attribute("href")
                if href and ("pdf" in href.lower() or "indir" in pl.text.lower()):
                    target_pdf = get_full_url(href)
                    break
            
            if target_pdf:
                data["pdf_url"] = target_pdf
                # PDF İndir ve Oku
                print(f"      📄 PDF İndiriliyor...")
                resp = requests.get(target_pdf, headers=HEADERS, verify=False, timeout=30)
                if resp.status_code == 200:
                    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                        full_text = ""
                        for p in pdf.pages:
                            full_text += p.extract_text() or ""
                            full_text += tabloyu_markdown_yap(p)
                        data["icerik"] = full_text
                        print(f"      ✅ PDF Okundu ({len(full_text)} karakter)")
                else:
                    print(f"      ⛔ PDF İndirme Hatası: {resp.status_code}")
        except Exception as e:
            print(f"      ⚠️ PDF işleme hatası: {e}")

        # PDF yoksa HTML içeriği al
        if len(data["icerik"]) < 50:
            data["icerik"] = driver.find_element(By.TAG_NAME, "body").text
            data["pdf_url"] = "HTML İçerik"

        return data
    except Exception as e:
        print(f"   ❌ Sayfa hatası: {e}")
        return None

def verileri_guncelle():
    print(f"🚀 Başlatılıyor: TÜRMOB Scraper V5 (Filtreli Mod)...")
    
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--enable-javascript") 
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.maximize_window()
    tum_veriler = []
    
    try:
        # 1. ANA SAYFAYA GİT
        driver.get(START_URL)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(3)

        # 2. YIL LİNKLERİNİ TOPLA
        print("📂 Yıl klasörleri taranıyor...")
        
        # Sadece içerik alanındaki linklere bak (layout-container)
        year_elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'layout-container')]//ul//li//a")
        
        year_urls = []
        for el in year_elements:
            try:
                txt = el.text.strip()
                href = el.get_attribute("href")
                
                clean_txt = ''.join(filter(str.isdigit, txt))
                
                if len(clean_txt) == 4 and href:
                    full_href = get_full_url(href)
                    year_val = int(clean_txt)
                    if 2000 < year_val < 2030:
                        year_urls.append({"yil": year_val, "url": full_href})
            except: continue

        year_urls.sort(key=lambda x: x["yil"], reverse=True)
        target_years = year_urls[:TARANACAK_YIL_ADEDI]
        
        if not target_years:
            print("❌ Yıl linkleri bulunamadı. Seçiciyi kontrol edin.")
            return

        print(f"📌 Bulunan Yıllar: {[y['yil'] for y in target_years]}")

        # 3. YILLARI DOLAŞ
        for year_obj in target_years:
            print(f"\n📂 YIL: {year_obj['yil']} ({year_obj['url']})")
            
            driver.get(year_obj["url"])
            time.sleep(2)
            
            # AY Linklerini Topla
            month_urls = []
            # Sadece içerik alanındaki linklere bak
            possible_months = driver.find_elements(By.XPATH, "//div[contains(@class, 'layout-container')]//ul//li//a")
            month_names = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", 
                           "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
            
            for m_el in possible_months:
                try:
                    mtxt = m_el.text.strip()
                    mhref = m_el.get_attribute("href")
                    if any(m in mtxt for m in month_names) and mhref:
                        month_urls.append(get_full_url(mhref))
                except: continue
            
            month_urls = list(set(month_urls))
            print(f"   🗓️ {len(month_urls)} ay bulundu.")

            # 4. AYLARI DOLAŞ
            for m_url in month_urls:
                print(f"   👉 Ay Taranıyor: {m_url}")
                driver.get(m_url)
                time.sleep(2)
                
                # SİRKÜLER LİNKLERİNİ BUL
                sirkuler_urls = []
                
                # ÖNEMLİ: Sadece layout-container içindeki linkleri al
                all_links = driver.find_elements(By.XPATH, "//div[contains(@class, 'layout-container')]//ul//li//a")
                
                # Yasaklı kelimeler (Header/Footer/Sidebar linklerini engellemek için)
                blacklist = ["hakkimizda", "iletisim", "disiplin", "kurul", "yonetim", "denetleme", "etk", "tesmer", "login", "uyelik"]

                for link in all_links:
                    try:
                        href = link.get_attribute("href")
                        
                        if href and len(href) > 40 and "pdf" not in href.lower():
                            full_sirkuler_url = get_full_url(href)
                            lower_url = full_sirkuler_url.lower()

                            # --- FİLTRELEME KURALLARI ---
                            # 1. URL içinde 'ekutuphane' geçmeli (Başka sitelere veya ana sayfaya gitmesin)
                            if "ekutuphane" not in lower_url:
                                continue
                            
                            # 2. Yasaklı kelimeler geçmemeli
                            if any(bad_word in lower_url for bad_word in blacklist):
                                continue

                            # 3. Kendisi veya üst menü olmamalı
                            if full_sirkuler_url != m_url and full_sirkuler_url != year_obj["url"]:
                                sirkuler_urls.append(full_sirkuler_url)
                    except: continue
                
                sirkuler_urls = list(set(sirkuler_urls))
                print(f"      🔗 {len(sirkuler_urls)} adet mevzuat sirküleri bulundu.")
                
                # 5. SİRKÜLERLERİ İŞLE
                for s_url in sirkuler_urls:
                    print(f"      ⬇️ İşleniyor: {s_url[-20:]}...") # URL'in son kısmını yazdır
                    data = process_sirkuler_page(driver, s_url)
                    if data:
                        tum_veriler.append(data)
                        
        # KAYDET
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(tum_veriler, f, ensure_ascii=False, indent=4)
        print(f"\n✅ İşlem bitti. {len(tum_veriler)} kayıt {OUTPUT_FILE} dosyasına yazıldı.")

    except Exception as e:
        print(f"❌ Beklenmedik Hata: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings()
    verileri_guncelle()