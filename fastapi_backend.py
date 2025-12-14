import json
import os
import time
import uuid
import difflib
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import google.generativeai as genai
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urljoin

# --- 1. AYARLAR VE SABİTLER ---
app = FastAPI(title="MüşavirGPT API", description="Mobil Uygulama İçin Vergi Asistanı Backend")

# API Anahtarı (Sunucuda Ortam Değişkeninden Alınır)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") 
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

DATA_FILE = "verginet_data.json"

# --- 2. VERİ MODELLERİ ---
class SoruIstegi(BaseModel):
    soru: str
    gecmis: Optional[List[dict]] = [] 

class CevapYaniti(BaseModel):
    cevap: str
    kaynaklar: List[str]

# --- 3. YARDIMCI FONKSİYONLAR ---
def get_chrome_options():
    options = Options()
    options.add_argument("--headless") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Sunucu ortamlarında (Linux/Docker) Chrome yolu farklı olabilir
    # Yaygın Linux yollarını kontrol edip ekliyoruz
    possible_paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser"
    ]
    for path in possible_paths:
        if os.path.exists(path):
            options.binary_location = path
            break
            
    return options

def get_best_model():
    """Sunucudaki API anahtarına uygun en iyi modeli bulur."""
    try:
        model_list = genai.list_models()
        supported = [m.name for m in model_list if 'generateContent' in m.supported_generation_methods]
        # Ücretli/Pro modeller öncelikli
        preferences = [
            'models/gemini-1.5-pro',
            'models/gemini-1.5-pro-latest',
            'models/gemini-2.0-flash-exp',
            'models/gemini-1.5-flash',
            'models/gemini-2.0-flash-lite-preview-02-05'
        ]
        for pref in preferences:
            if pref in supported: return pref
        for m in supported:
            if 'gemini' in m: return m
        return None
    except: return None

def extract_content_smart(driver, is_kanun=False):
    """Sayfa içeriğini akıllıca çeker (Akordeonları açar)."""
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        
        main_div = None
        # İçerik alanını bulmaya çalış
        for xpath in ["//*[contains(@id, 'pnlicerik')]", "//*[contains(@id, 'dvOzelge')]"]:
            try:
                main_div = driver.find_element(By.XPATH, xpath)
                break
            except: continue
        
        if not main_div:
            main_div = driver.find_element(By.TAG_NAME, "body")

        # Akordeon başlıklarını aç (Sadece Verginet için)
        if not is_kanun and "verginet" in driver.current_url:
            clickables = main_div.find_elements(By.CSS_SELECTOR, ".panel-heading, .panel-title, h4, h3, a[data-toggle='collapse']")
            click_count = 0
            for elem in clickables:
                if click_count > 100: break
                try:
                    if elem.is_displayed():
                        driver.execute_script("arguments[0].click();", elem)
                        click_count += 1
                        time.sleep(0.05)
                except: continue
            if click_count > 0: time.sleep(2)

        text = driver.execute_script("return arguments[0].innerText;", main_div)
        if not text or len(text) < 100:
             text = main_div.text
        return text
    except: return ""

# --- 4. GELİŞMİŞ ARKA PLAN TARAMA (OTOPİLOT) ---
def arka_plan_tarama():
    """
    Tüm arşivi (Yıllar ve Sayfalar) tarayan ana fonksiyon.
    Sunucuda tek seferlik tetiklenir veya zamanlanır.
    """
    print("🚀 [Scraper] Tam Kapsamlı Tarama Başlatıldı...")
    options = get_chrome_options()
    
    # 1. Mevcut veriyi yükle (Kümülatif)
    veri_listesi = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                veri_listesi = json.load(f)
        except: pass

    # 2. Görev Listesini Hazırla (2015-2025 Arşivi)
    gorevler = []
    
    # A. Vergi Sirküleri (2015-2025)
    for yil in range(2025, 2014, -1):
        gorevler.append({
            "base_url": f"https://www.verginet.net/sirkulerler.aspx?Yil={yil}&TipID=1",
            "etiket": f"Sirküler {yil}",
            "paginated": True
        })
        
    # B. Özelgeler (2015-2025)
    for yil in range(2025, 2014, -1):
        gorevler.append({
            "base_url": f"https://www.verginet.net/dtt/Ozelgeler.aspx?Yil={yil}",
            "etiket": f"Özelge {yil}",
            "paginated": True
        })

    # C. Temel Kanunlar (Tek Sayfa)
    gorevler.append({"base_url": "https://www.verginet.net/dtt/7/TemelVergiKanunlari_4.aspx", "etiket": "Temel Kanun", "paginated": False, "is_kanun": True})
    gorevler.append({"base_url": "https://www.verginet.net/dtt/7/DigerVergiKanunlari_6.aspx", "etiket": "Diğer Kanun", "paginated": False, "is_kanun": True})

    driver = None
    yeni_veri_sayisi = 0
    MAX_SAYFA = 50 # Her yıl için taranacak maksimum sayfa sayısı
    
    try:
        try:
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        except:
            # Docker/Linux ortamında bazen path manuel verilmelidir, yukarıdaki get_chrome_options bunu halleder
            driver = webdriver.Chrome(options=options)

        # --- GÖREV DÖNGÜSÜ ---
        for task in gorevler:
            is_paginated = task.get("paginated")
            
            # Sayfa Döngüsü (1'den başlar, link bitene kadar gider)
            # Eğer sayfalama yoksa sadece 1 kere döner.
            sayfa_limiti = MAX_SAYFA if is_paginated else 1
            
            for page_num in range(sayfa_limiti):
                
                # URL Oluştur
                if is_paginated:
                    sep = "&" if "?" in task["base_url"] else "?"
                    current_url = f"{task['base_url']}{sep}PageIndex={page_num}"
                    current_etiket = f"{task['etiket']} - S.{page_num}"
                else:
                    current_url = task["base_url"]
                    current_etiket = task["etiket"]
                
                print(f"📂 Taranıyor: {current_etiket}")
                
                try:
                    driver.get(current_url)
                    time.sleep(3)
                    
                    # Linkleri Bul
                    detay_linkleri = []
                    try:
                        xpath = "//*[contains(@id, 'DGSirkulerler')]" if is_paginated else "//*[contains(@id, 'pnlicerik')]"
                        try: container = driver.find_element(By.XPATH, xpath)
                        except: container = driver.find_element(By.TAG_NAME, "body")
                        
                        links = container.find_elements(By.TAG_NAME, "a")
                        for l in links:
                            try:
                                h = l.get_attribute("href")
                                t = l.text.strip()
                                if h and t and "/dtt/" in h and h != current_url and "javascript" not in h:
                                    full_url = urljoin(current_url, h)
                                    detay_linkleri.append((t, full_url))
                            except: continue
                        
                        detay_linkleri = list(set(detay_linkleri))
                    except: pass
                    
                    # Eğer sayfa boşsa, bu yıl/kategori bitmiştir. Sonraki göreve geç.
                    if not detay_linkleri and is_paginated:
                        print(f"⏹️ {task['etiket']} tamamlandı (Boş sayfa).")
                        break 
                    
                    # --- İÇERİĞE GİR VE ÇEK ---
                    for baslik, url in detay_linkleri:
                        # Mükerrer Kontrolü (Hız kazandırır)
                        if any(d['url'] == url for d in veri_listesi): continue
                        
                        try:
                            driver.get(url)
                            time.sleep(1.5)
                            
                            # Kanun Modu: "Tüm Kanun" linkine git
                            if task.get("is_kanun"):
                                try:
                                    tum_link = driver.find_element(By.PARTIAL_LINK_TEXT, "Tüm Kanun")
                                    if tum_link:
                                        yeni_url = tum_link.get_attribute('href')
                                        driver.get(yeni_url)
                                        time.sleep(2)
                                        url = yeni_url
                                except: pass

                            icerik = extract_content_smart(driver, is_kanun=task.get("is_kanun", False))
                            
                            if len(icerik) > 300:
                                veri_listesi.append({
                                    "id": str(uuid.uuid4()),
                                    "baslik": baslik,
                                    "icerik": icerik,
                                    "url": url,
                                    "kategori": task['etiket'],
                                    "tarih": datetime.now().strftime("%Y-%m-%d %H:%M")
                                })
                                yeni_veri_sayisi += 1
                                
                                # Düzenli Kayıt (Veri kaybını önle)
                                if yeni_veri_sayisi % 5 == 0:
                                    with open(DATA_FILE, "w", encoding="utf-8") as f:
                                        json.dump(veri_listesi, f, ensure_ascii=False, indent=4)
                                        print(f"💾 Kaydedildi: {yeni_veri_sayisi} veri...")
                        except: continue

                except Exception as page_err:
                    print(f"⚠️ Sayfa hatası: {page_err}")
                    continue
                    
        # Final Kayıt
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(veri_listesi, f, ensure_ascii=False, indent=4)
            
        print(f"✅ [Scraper] Bitti. Toplam {yeni_veri_sayisi} yeni kayıt eklendi.")
        
    except Exception as e:
        print(f"❌ [Scraper] Kritik Hata: {e}")
    finally:
        if driver: driver.quit()

# --- 5. API UÇ NOKTALARI (ENDPOINTS) ---

@app.get("/")
def home():
    return {"durum": "aktif", "mesaj": "MüşavirGPT Sunucusu Çalışıyor 🚀"}

@app.get("/status")
def get_status():
    """Veri durumunu kontrol eder."""
    count = 0
    last_mod = "Bilinmiyor"
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                count = len(data)
            last_mod = time.ctime(os.path.getmtime(DATA_FILE))
        except: pass
    
    return {"toplam_belge": count, "son_guncelleme": last_mod}

@app.post("/tetikle-tarama")
def trigger_scrape(background_tasks: BackgroundTasks):
    """
    Bu adrese istek atıldığında, sunucu arka planda taramaya başlar.
    """
    background_tasks.add_task(arka_plan_tarama)
    return {"mesaj": "Tam kapsamlı tarama arka planda başlatıldı."}

@app.post("/sor", response_model=CevapYaniti)
def ask_question(request: SoruIstegi):
    """
    Mobil uygulamadan gelen soruyu alır, veritabanını tarar ve cevap döner.
    """
    if not GOOGLE_API_KEY:
        print("UYARI: API Anahtarı eksik, cevap üretilemeyebilir.")

    # 1. Veriyi Yükle
    context_data = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                context_data = json.load(f)
        except: pass
    
    if not context_data:
        return CevapYaniti(cevap="Henüz veri tabanım boş. Lütfen taramayı tetikleyin.", kaynaklar=[])

    # 2. Arama Algoritması (Basitleştirilmiş)
    soru_kelimeleri = request.soru.lower().split()
    bulunanlar = []
    
    for item in context_data:
        puan = 0
        baslik = item['baslik'].lower()
        if request.soru.lower() in baslik: puan += 500
        matches = sum(1 for k in soru_kelimeleri if k in baslik)
        if matches > 0: puan += matches * 50
        if puan > 0: bulunanlar.append((puan, item))
    
    bulunanlar.sort(key=lambda x: x[0], reverse=True)
    en_iyi_belgeler = [b[1] for b in bulunanlar[:2]] 

    if not en_iyi_belgeler:
        return CevapYaniti(cevap="Veri setimde bu konuyla ilgili bilgi bulamadım.", kaynaklar=[])

    # 3. Prompt Hazırlama
    context_text = ""
    kaynak_isimleri = []
    for doc in en_iyi_belgeler:
        # Metin temizliği
        icerik_temiz = doc['icerik'].replace("\n", " ").strip()
        context_text += f"\n--- KAYNAK: {doc['baslik']} ---\n{icerik_temiz[:40000]}\n" # Pro model için yüksek limit
        kaynak_isimleri.append(doc['baslik'])

    prompt = f"""
    Sen uzman bir Vergi Asistanısın.
    KAYNAKLAR: {context_text}
    SORU: {request.soru}
    TALİMAT: Soruyu sadece kaynaklara dayanarak cevapla.
    """

    # 4. Yapay Zeka Çağrısı
    try:
        active_model = get_best_model() or 'models/gemini-1.5-pro'
        model = genai.GenerativeModel(active_model)
        response = model.generate_content(prompt)
        return CevapYaniti(cevap=response.text, kaynaklar=kaynak_isimleri)
    except Exception as e:
        return CevapYaniti(cevap=f"Hata oluştu: {str(e)}", kaynaklar=[])

if __name__ == "__main__":
    import uvicorn
    # Sunucu portunu ortam değişkeninden al, yoksa 8000
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)