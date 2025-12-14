import json
import os
import time
import uuid
import difflib
from datetime import datetime
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
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
    HTML yapısına (pnlicerik / dvOzelge) göre optimize edilmiştir.
    """
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        
        main_div = None
        # Verginet içerik alanları (Senin HTML'ine göre)
        for xpath in ["//*[contains(@id, 'pnlicerik')]", "//*[contains(@id, 'dvOzelge')]"]:
            try:
                main_div = driver.find_element(By.XPATH, xpath)
                break
            except: continue
        
        if not main_div:
            main_div = driver.find_element(By.TAG_NAME, "body")

        # Özelge Sayfasıysa Akordeonları Aç (Sadece Verginet)
        if not is_kanun and "verginet" in driver.current_url:
            # Senin HTML'inde accordion div'i var, içindeki başlıkları bulup tıklıyoruz
            clickables = main_div.find_elements(By.CSS_SELECTOR, ".panel-heading, .panel-title, h4, h3, a[data-toggle='collapse']")
            for i, elem in enumerate(clickables):
                if i > 50: break # Sonsuz döngü koruması
                try:
                    if elem.is_displayed():
                        driver.execute_script("arguments[0].click();", elem)
                        time.sleep(0.05)
                except: continue
            time.sleep(2) # Açılma animasyonu için bekle

        text = driver.execute_script("return arguments[0].innerText;", main_div)
        if not text or len(text) < 100:
             text = main_div.text
        return text
    except: return ""

# --- 5. ARKA PLAN TARAMA İŞLEMİ (ANA MOTOR) ---
def arka_plan_tarama():
    print(f"🚀 [Otopilot] 10 Yıllık Tarama Başlatıldı: {datetime.now()}")
    options = get_chrome_options()
    
    veri_listesi = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                veri_listesi = json.load(f)
        except: pass

    # --- GÖREV LİSTESİ (10 YIL) ---
    gorevler = []
    
    # 2025'ten 2015'e kadar (Geriye doğru)
    for yil in range(2025, 2014, -1):
        # 1. Özelgeler
        gorevler.append({
            "base_url": f"https://www.verginet.net/dtt/Ozelgeler.aspx?Yil={yil}",
            "etiket": f"Özelge {yil}",
            "paginated": True
        })
        # 2. Vergi Sirküleri
        gorevler.append({
            "base_url": f"https://www.verginet.net/sirkulerler.aspx?Yil={yil}&TipID=1",
            "etiket": f"Sirküler {yil}",
            "paginated": True
        })

    driver = None
    yeni_veri_sayisi = 0
    # Her yıl için kaç sayfa taranacağı (Otomatik durur ama güvenlik için limit koyduk)
    MAX_SAYFA_DERINLIGI = 50 
    
    try:
        try:
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        except:
            driver = webdriver.Chrome(options=options)

        for task in gorevler:
            # Sayfa Döngüsü (PageIndex=0, 1, 2...)
            for page_num in range(MAX_SAYFA_DERINLIGI):
                
                # URL Oluşturma
                sep = "&" if "?" in task["base_url"] else "?"
                current_url = f"{task['base_url']}{sep}PageIndex={page_num}"
                
                print(f"📂 Taranıyor: {task['etiket']} - Sayfa {page_num}")
                
                try:
                    driver.get(current_url)
                    time.sleep(3)
                    
                    # Linkleri Bul (HTML'deki DGSirkulerler tablosu)
                    detay_linkleri = []
                    try:
                        # Senin gönderdiğin HTML'deki tablo ID'si
                        xpath = "//*[contains(@id, 'DGSirkulerler')]" 
                        try: container = driver.find_element(By.XPATH, xpath)
                        except: container = driver.find_element(By.TAG_NAME, "body")
                        
                        links = container.find_elements(By.TAG_NAME, "a")
                        for l in links:
                            try:
                                h = l.get_attribute("href")
                                t = l.text.strip()
                                # Link filtresi (Javascript ve boş olanları atla)
                                if h and t and "/dtt/" in h and "javascript" not in h and h != current_url:
                                    full_url = urljoin(current_url, h)
                                    detay_linkleri.append((t, full_url))
                            except: continue
                        
                        detay_linkleri = list(set(detay_linkleri))
                    except: pass
                    
                    # Eğer bu sayfada hiç link yoksa, bu yıl bitmiş demektir. Sonraki yıla geç.
                    if not detay_linkleri:
                        print(f"⏹️ {task['etiket']} tamamlandı (Sayfa {page_num} boş).")
                        break 
                    
                    # İçeriğe Gir ve Çek
                    for baslik, url in detay_linkleri:
                        # Mükerrer Kontrolü (Aynısı varsa atla)
                        if any(d['url'] == url for d in veri_listesi): continue
                        
                        try:
                            driver.get(url)
                            time.sleep(1.5)
                            
                            icerik = extract_content_smart(driver)
                            
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
                                
                                # Anlık Kayıt (Veri kaybı olmasın)
                                if yeni_veri_sayisi % 5 == 0:
                                    with open(DATA_FILE, "w", encoding="utf-8") as f:
                                        json.dump(veri_listesi, f, ensure_ascii=False, indent=4)
                                        print(f"💾 {yeni_veri_sayisi}. veri kaydedildi...")
                        except: continue
                except Exception as page_err:
                    print(f"⚠️ Sayfa hatası: {page_err}")
                    continue
                    
        # Final Kayıt
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(veri_listesi, f, ensure_ascii=False, indent=4)
            
        print(f"✅ [Otopilot] Tur tamamlandı. Toplam {yeni_veri_sayisi} yeni veri eklendi.")
        
    except Exception as e:
        print(f"❌ [Otopilot] Kritik Hata: {e}")
    finally:
        if driver: driver.quit()

# --- 6. API UÇ NOKTALARI (ENDPOINTS) ---
@app.get("/")
def home():
    return {"durum": "aktif", "mesaj": "MüşavirGPT Otonom Sunucusu Çalışıyor 🚀"}

# --- YENİ PATRON PANELİ (DASHBOARD) ---
@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    """Tarayıcıdan girilebilen, şık ve canlı durum paneli."""
    
    # 1. Verileri Oku
    count = 0
    last_mod = "Veri Yok"
    son_baslik = "-"
    son_5_veri = []
    
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                count = len(data)
                if data:
                    son_baslik = data[-1].get("baslik", "-")
                    # Son 5 veriyi al (Tersine çevirip)
                    son_5_veri = data[-5:][::-1]
            
            # Son güncelleme zamanı
            mtime = os.path.getmtime(DATA_FILE)
            last_mod = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        except: pass
    
    # 2. Zamanlayıcı Durumu
    next_run = "Bilinmiyor"
    try:
        jobs = scheduler.get_jobs()
        if jobs:
            next_run = str(jobs[0].next_run_time)
    except: pass
    
    # 3. HTML Şablonu (Modern ve Şık Tasarım)
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>MüşavirGPT Kontrol Paneli</title>
        <meta http-equiv="refresh" content="30"> <!-- 30 saniyede bir yenile -->
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; padding: 20px; }}
            .container {{ max-width: 900px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            h1 {{ color: #2c3e50; text-align: center; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
            .status-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-top: 20px; }}
            .card {{ background: #ecf0f1; padding: 20px; border-radius: 8px; text-align: center; }}
            .card h3 {{ margin: 0; color: #7f8c8d; font-size: 14px; }}
            .card p {{ margin: 10px 0 0; font-size: 24px; font-weight: bold; color: #2c3e50; }}
            .live-indicator {{ color: #27ae60; font-weight: bold; animation: pulse 2s infinite; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 30px; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #3498db; color: white; }}
            tr:hover {{ background-color: #f5f5f5; }}
            @keyframes pulse {{ 0% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} 100% {{ opacity: 1; }} }}
            .btn-refresh {{ display: block; width: 100%; padding: 10px; background: #2c3e50; color: white; text-align: center; text-decoration: none; margin-top: 20px; border-radius: 5px; }}
            .btn-refresh:hover {{ background: #34495e; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🕷️ MüşavirGPT <span style="font-size:0.6em; color:#7f8c8d;">Otopilot Paneli</span></h1>
            <p style="text-align: center;">Sistem Durumu: <span class="live-indicator">● ÇALIŞIYOR</span></p>
            
            <div class="status-grid">
                <div class="card">
                    <h3>TOPLAM BELGE</h3>
                    <p>{count}</p>
                </div>
                <div class="card">
                    <h3>SON GÜNCELLEME</h3>
                    <p style="font-size: 16px;">{last_mod}</p>
                </div>
                <div class="card">
                    <h3>SIRADAKİ TARAMA</h3>
                    <p style="font-size: 16px;">{next_run.split('+')[0]}</p>
                </div>
            </div>

            <h2>📥 Son Eklenen Veriler</h2>
            <table>
                <thead>
                    <tr>
                        <th>Başlık</th>
                        <th>Kategori</th>
                        <th>İndirilme Tarihi</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    # Tablo satırlarını ekle
    for item in son_5_veri:
        html_content += f"""
        <tr>
            <td><a href="{item.get('url', '#')}" target="_blank">{item.get('baslik', 'Bilinmiyor')}</a></td>
            <td>{item.get('kategori', '-')}</td>
            <td>{item.get('tarih', '-')}</td>
        </tr>
        """
        
    html_content += """
                </tbody>
            </table>
            <br>
            <div style="text-align:center; color: #7f8c8d; font-size: 12px;">
                Bu sayfa her 30 saniyede bir otomatik yenilenir.
            </div>
            
            <form action="/tetikle-tarama" method="post" style="text-align:center; margin-top:20px;">
                <button type="submit" style="background:#e74c3c; color:white; border:none; padding:10px 20px; border-radius:5px; cursor:pointer;">
                    🚨 Acil Tarama Başlat (Manuel)
                </button>
            </form>
        </div>
    </body>
    </html>
    """
    return html_content

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
        context_text += f"\n--- KAYNAK: {doc['baslik']} ---\n{icerik_temiz[:40000]}\n"
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