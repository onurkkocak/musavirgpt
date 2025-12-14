import json
import os
import time
import uuid
import difflib
from datetime import datetime
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import google.generativeai as genai
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urljoin

# --- ZAMANLAYICI (OTONOM SİSTEM) ---
from apscheduler.schedulers.background import BackgroundScheduler

# --- 1. AYARLAR VE SABİTLER ---
DATA_FILE = "verginet_data.json"
TARAMA_ARALIGI_SAAT = 1 # Her saat başı kontrol et

# API Anahtarı
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") 
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

# --- 2. ZAMANLAYICI MOTORU ---
scheduler = BackgroundScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("⏰ [Zamanlayıcı] MüşavirGPT Otonom Modu Başlatılıyor...")
    # Sunucu başlar başlamaz bir tarama başlat (Test için)
    scheduler.add_job(arka_plan_tarama, 'date', run_date=datetime.now())
    # Sonra her saat başı tekrarla
    scheduler.add_job(arka_plan_tarama, 'interval', hours=TARAMA_ARALIGI_SAAT)
    scheduler.start()
    yield 
    print("💤 [Zamanlayıcı] Kapatılıyor...")
    scheduler.shutdown()

app = FastAPI(title="MüşavirGPT API", lifespan=lifespan)

# --- 3. VERİ MODELLERİ ---
class SoruIstegi(BaseModel):
    soru: str
    gecmis: Optional[List[dict]] = [] 

class CevapYaniti(BaseModel):
    cevap: str
    kaynaklar: List[str]

# --- 4. YARDIMCI FONKSİYONLAR ---
def get_chrome_options():
    options = Options()
    options.add_argument("--headless") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Linux/Server yolları
    possible_paths = ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]
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
        preferences = [
            'models/gemini-2.0-flash-lite-preview-02-05',
            'models/gemini-1.5-pro',
            'models/gemini-2.0-flash',
            'models/gemini-1.5-flash'
        ]
        for pref in preferences:
            if pref in supported: return pref
        return supported[0] if supported else None
    except: return None

def extract_content_smart(driver, is_kanun=False):
    """
    Sayfa içeriğini çeker. Özelgeler için akordeonları açar.
    """
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        
        main_div = None
        # İçerik alanı bulma (Verginet & KPMG Genel)
        for xpath in ["//*[contains(@id, 'pnlicerik')]", "//*[contains(@id, 'dvOzelge')]"]:
            try:
                main_div = driver.find_element(By.XPATH, xpath)
                break
            except: continue
        
        if not main_div:
            # KPMG gibi siteler için en büyük metin bloğunu bul
            try:
                divs = driver.find_elements(By.TAG_NAME, "div")
                valid_divs = [d for d in divs if d.is_displayed() and len(d.text) > 200]
                if valid_divs:
                    main_div = max(valid_divs, key=lambda d: len(d.text))
                else:
                    main_div = driver.find_element(By.TAG_NAME, "body")
            except:
                main_div = driver.find_element(By.TAG_NAME, "body")

        # Özelge Sayfasıysa Akordeonları Aç (Sadece Verginet)
        if not is_kanun and "verginet" in driver.current_url:
            clickables = main_div.find_elements(By.CSS_SELECTOR, ".panel-heading, .panel-title, h4, h3, a[data-toggle='collapse']")
            for i, elem in enumerate(clickables):
                if i > 50: break 
                try:
                    if elem.is_displayed():
                        driver.execute_script("arguments[0].click();", elem)
                        time.sleep(0.05)
                except: continue
            time.sleep(2) 

        text = driver.execute_script("return arguments[0].innerText;", main_div)
        if not text or len(text) < 100:
             text = main_div.text
        return text
    except: return ""

# --- 5. ARKA PLAN TARAMA İŞLEMİ (ANA MOTOR) ---
def arka_plan_tarama():
    print(f"🚀 [Otopilot] Çoklu Kaynak Taraması Başlatıldı: {datetime.now()}")
    options = get_chrome_options()
    
    veri_listesi = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                veri_listesi = json.load(f)
        except: pass

    # --- GÖREV LİSTESİ (VERGİNET + KPMG) ---
    gorevler = []
    
    # 1. KPMG KAYNAKLARI (Güncel ve Önemli)
    # KPMG'de sayfalama 'p' parametresi ile yapılır ve 1'den başlar.
    kpmg_sources = [
        ("KPMG Duyurular", "https://kpmgvergi.com/yayinlar/mali-bultenler?category=duyurular&categoryId=5"),
        ("KPMG Vergi", "https://kpmgvergi.com/yayinlar/mali-bultenler?category=vergi&categoryId=1"),
        ("KPMG Gümrük", "https://kpmgvergi.com/yayinlar/mali-bultenler?category=gumruk&categoryId=2"),
        ("KPMG SGK", "https://kpmgvergi.com/yayinlar/mali-bultenler?category=sosyal-guvenlik&categoryId=3")
    ]
    
    for etiket, url in kpmg_sources:
        gorevler.append({
            "base_url": url,
            "etiket": etiket,
            "paginated": True,
            "param": "p",      # KPMG sayfa parametresi
            "start_page": 1    # KPMG 1. sayfadan başlar
        })

    # 2. VERGİNET KAYNAKLARI (Son 2 Yıl - Hız İçin)
    for yil in range(2025, 2023, -1):
        gorevler.append({
            "base_url": f"https://www.verginet.net/dtt/Ozelgeler.aspx?Yil={yil}",
            "etiket": f"Özelge {yil}",
            "paginated": True,
            "param": "PageIndex", # Verginet sayfa parametresi
            "start_page": 0       # Verginet 0. sayfadan başlar
        })
        gorevler.append({
            "base_url": f"https://www.verginet.net/sirkulerler.aspx?Yil={yil}&TipID=1",
            "etiket": f"Sirküler {yil}",
            "paginated": True,
            "param": "PageIndex",
            "start_page": 0
        })
        
    # 3. VERGİNET KANUNLARI (Tek Seferlik - Hiyerarşik olmayan)
    gorevler.append({"base_url": "https://www.verginet.net/dtt/7/TemelVergiKanunlari_4.aspx", "etiket": "Temel Kanun", "paginated": False, "is_kanun": True})

    driver = None
    yeni_veri_sayisi = 0
    MAX_SAYFA_DERINLIGI = 10 # Her kaynak için en fazla kaç sayfa gidilsin?
    
    try:
        try:
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        except:
            driver = webdriver.Chrome(options=options)

        for task in gorevler:
            is_paginated = task.get("paginated")
            param_name = task.get("param", "PageIndex")
            start_page = task.get("start_page", 0)
            
            # Sayfa Döngüsü
            sayfa_limiti = MAX_SAYFA_DERINLIGI if is_paginated else 1
            
            for i in range(sayfa_limiti):
                page_num = start_page + i
                
                # URL Oluştur
                if is_paginated:
                    sep = "&" if "?" in task["base_url"] else "?"
                    current_url = f"{task['base_url']}{sep}{param_name}={page_num}"
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
                        # Verginet için özel, diğerleri için genel yapı
                        xpath = "//*[contains(@id, 'DGSirkulerler')]" if "verginet" in current_url and is_paginated else "//*[contains(@id, 'pnlicerik')]"
                        
                        try: container = driver.find_element(By.XPATH, xpath)
                        except: container = driver.find_element(By.TAG_NAME, "body")
                        
                        links = container.find_elements(By.TAG_NAME, "a")
                        for l in links:
                            try:
                                h = l.get_attribute("href")
                                t = l.text.strip()
                                
                                if h and t and "javascript" not in h and h != current_url:
                                    # URL Düzeltme (Relative to Absolute)
                                    full_url = urljoin(current_url, h)
                                    
                                    # Filtreler
                                    if "verginet" in current_url:
                                        if "/dtt/" in full_url: detay_linkleri.append((t, full_url))
                                    elif "kpmg" in current_url:
                                        # KPMG makale linkleri genellikle 'makale' veya 'yayin' içerir ve category parametresi taşımaz
                                        if full_url != current_url and len(t) > 10:
                                            detay_linkleri.append((t, full_url))
                                    else:
                                        detay_linkleri.append((t, full_url))
                                        
                            except: continue
                        
                        detay_linkleri = list(set(detay_linkleri))
                    except: pass
                    
                    # Sayfa boşsa bitir
                    if not detay_linkleri and is_paginated:
                        print(f"⏹️ {task['etiket']} tamamlandı (Boş sayfa).")
                        break 
                    
                    # --- İÇERİĞE GİR VE ÇEK ---
                    for baslik, url in detay_linkleri:
                        if any(d['url'] == url for d in veri_listesi): continue
                        
                        try:
                            driver.get(url)
                            time.sleep(1.5)
                            
                            # Verginet Kanun Modu: "Tüm Kanun" linkine git
                            if task.get("is_kanun") and "verginet" in url:
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
                                
                                if yeni_veri_sayisi % 5 == 0:
                                    with open(DATA_FILE, "w", encoding="utf-8") as f:
                                        json.dump(veri_listesi, f, ensure_ascii=False, indent=4)
                                        print(f"💾 Kaydedildi: {yeni_veri_sayisi} veri...")
                        except: continue
                except Exception as page_err:
                    print(f"⚠️ Sayfa hatası: {page_err}")
                    continue
                    
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(veri_listesi, f, ensure_ascii=False, indent=4)
            
        print(f"✅ [Otopilot] Tur tamamlandı. Toplam {yeni_veri_sayisi} yeni kayıt eklendi.")
        
    except Exception as e:
        print(f"❌ [Otopilot] Kritik Hata: {e}")
    finally:
        if driver: driver.quit()

# --- 6. API UÇ NOKTALARI (ENDPOINTS) ---

@app.get("/")
def home():
    return {"durum": "aktif", "mesaj": "MüşavirGPT Otonom Sunucusu Çalışıyor 🚀"}

@app.get("/status")
def get_status():
    count = 0
    last_mod = "Bilinmiyor"
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                count = len(data)
            last_mod = time.ctime(os.path.getmtime(DATA_FILE))
        except: pass
    
    next_run = "Bilinmiyor"
    try:
        jobs = scheduler.get_jobs()
        if jobs: next_run = str(jobs[0].next_run_time)
    except: pass
    
    return {"toplam_belge": count, "son_dosya_guncellemesi": last_mod, "siradaki_tarama": next_run}

@app.post("/tetikle-tarama")
def trigger_scrape(background_tasks: BackgroundTasks):
    background_tasks.add_task(arka_plan_tarama)
    return {"mesaj": "Manuel tarama başlatıldı."}

@app.post("/sor", response_model=CevapYaniti)
def ask_question(request: SoruIstegi):
    if not GOOGLE_API_KEY: print("UYARI: API Anahtarı eksik.")

    context_data = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                context_data = json.load(f)
        except: pass
    
    if not context_data:
        return CevapYaniti(cevap="Veri tabanım henüz oluşuyor...", kaynaklar=[])

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
        return CevapYaniti(cevap="İlgili bilgi bulunamadı.", kaynaklar=[])

    context_text = ""
    kaynak_isimleri = []
    for doc in en_iyi_belgeler:
        icerik_temiz = doc['icerik'].replace("\n", " ").strip()
        context_text += f"\n--- KAYNAK: {doc['baslik']} ({doc['kategori']}) ---\n{icerik_temiz[:40000]}\n"
        kaynak_isimleri.append(doc['baslik'])

    prompt = f"""
    Sen uzman bir Vergi Asistanısın.
    KAYNAKLAR: {context_text}
    SORU: {request.soru}
    TALİMAT: Soruyu sadece kaynaklara dayanarak cevapla.
    """

    try:
        active_model = get_best_model() or 'models/gemini-1.5-pro'
        model = genai.GenerativeModel(active_model)
        response = model.generate_content(prompt)
        return CevapYaniti(cevap=response.text, kaynaklar=kaynak_isimleri)
    except Exception as e:
        return CevapYaniti(cevap=f"Hata: {str(e)}", kaynaklar=[])

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)