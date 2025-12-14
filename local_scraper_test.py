import streamlit as st
import time
import pandas as pd
import json
import uuid
import os
import difflib # Metin benzerliği için eklendi
from datetime import datetime
import requests 
import google.generativeai as genai
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from urllib.parse import urljoin

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="MüşavirGPT - Mevzuat ve Özelge Tarayıcı", layout="wide")

st.title("🕷️ MüşavirGPT: Tam Kapsamlı Arşiv Tarayıcısı")
st.info("Bu modül, Vergi Kanunları'nı, Özelgeleri ve KPMG Bültenlerini akıllıca tarar ve arşivler.")

# --- API ANAHTARI ---
api_key = None
try:
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
except: pass

if not api_key:
    with st.sidebar:
        api_key = st.text_input("Google API Key", type="password")
if api_key:
    genai.configure(api_key=api_key)

# --- TARAMA MODU SEÇİMİ ---
st.sidebar.header("Tarama Ayarları")
TARAMA_MODU = st.sidebar.radio(
    "Hangi Veriyi Çekmek İstiyorsunuz?", 
    [
        "Vergi Sirküleri (2015-2025)", 
        "Özelgeler (2015-2025 Arşivi)", 
        "KPMG - Duyurular",
        "KPMG - Vergi Bültenleri",
        "KPMG - Gümrük Bültenleri",
        "KPMG - SGK Bültenleri",
        "Temel Vergi Kanunları",
        "Diğer Vergi Kanunları",
        "Vergi Yargısı Mevzuatı",
        "Gerekçeli Vergi Kanunları",
        "Çifte Vergilendirmeyi Önleme Anlaşmaları",
        "Tekil URL Tarama (Manuel)"
    ]
)

# --- SAYFA DERİNLİĞİ AYARI ---
MAX_SAYFA_LIMITI = 1
if any(x in TARAMA_MODU for x in ["Sirküleri", "Özelgeler", "KPMG"]):
    MAX_SAYFA_LIMITI = st.sidebar.number_input(
        "Maksimum Tarama Derinliği (Sayfa)", 
        min_value=1, 
        value=50, 
        help="Sistem link buldukça ilerler. KPMG'de p=1, p=2... şeklinde gider."
    )

# --- AKILLI MODEL SEÇİCİ ---
def get_best_model():
    try:
        model_list = genai.list_models()
        supported_models = [m.name for m in model_list if 'generateContent' in m.supported_generation_methods]
        preferences = [
            'models/gemini-2.0-flash-lite-preview-02-05',
            'models/gemini-2.0-flash-lite',
            'models/gemini-2.0-flash',
            'models/gemini-1.5-pro',
            'models/gemini-1.5-flash',
            'models/gemini-pro'
        ]
        for pref in preferences:
            if pref in supported_models: return pref
        for m in supported_models:
            if 'gemini' in m: return m
        return None
    except: return None

# --- DRIVER AYARLARI ---
def get_chrome_options():
    options = Options()
    options.add_argument("--headless") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage") 
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    if os.path.exists("/usr/bin/chromium"): options.binary_location = "/usr/bin/chromium"
    elif os.path.exists("/usr/bin/chromium-browser"): options.binary_location = "/usr/bin/chromium-browser"
    return options

# --- AKILLI İÇERİK ÇIKARICI ---
def extract_content_smart(driver, is_kanun=False):
    """
    Sayfa tipine göre (Kanun vs Özelge vs KPMG) en uygun içeriği çeker.
    """
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        main_div = None
        try:
            main_div = driver.find_element(By.XPATH, "//*[contains(@id, 'pnlicerik')]")
        except:
            try:
                main_div = driver.find_element(By.XPATH, "//*[contains(@id, 'dvOzelge')]")
            except:
                try:
                    divs = driver.find_elements(By.TAG_NAME, "div")
                    valid_divs = [d for d in divs if d.is_displayed() and len(d.text) > 100]
                    if valid_divs:
                        main_div = max(valid_divs, key=lambda d: len(d.text))
                    else:
                         main_div = driver.find_element(By.TAG_NAME, "body")
                except:
                    main_div = driver.find_element(By.TAG_NAME, "body")

        if not is_kanun and "verginet" in driver.current_url:
            clickables = main_div.find_elements(By.CSS_SELECTOR, ".panel-heading, .panel-title, h4, h3, a[data-toggle='collapse']")
            click_count = 0
            for elem in clickables:
                if click_count > 150: break
                try:
                    if elem.is_displayed():
                        driver.execute_script("arguments[0].click();", elem)
                        click_count += 1
                        time.sleep(0.05)
                except: continue
            if click_count > 0: time.sleep(2)

        if main_div:
            text = driver.execute_script("return arguments[0].innerText;", main_div)
            if not text or len(text) < 100:
                text = main_div.text
            return text
        
        return driver.find_element(By.TAG_NAME, "body").text

    except Exception as e:
        return f"İçerik okunamadı: {str(e)}"

# --- 1. ANA TARAMA FONKSİYONU ---
def taramayi_baslat():
    status_box = st.empty()
    options = get_chrome_options()
    veri_listesi = []
    
    if os.path.exists("verginet_data.json"):
        try:
            with open("verginet_data.json", "r", encoding="utf-8") as f:
                veri_listesi = json.load(f)
        except: pass

    driver = None
    try:
        try:
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        except:
            driver = webdriver.Chrome(options=options)

        gorevler = [] 
        
        if "Vergi Sirküleri" in TARAMA_MODU:
             for yil in range(2025, 2014, -1):
                gorevler.append({
                    "base_url": f"https://www.verginet.net/sirkulerler.aspx?Yil={yil}&TipID=1",
                    "etiket": f"Sirküler {yil}",
                    "paginated": True,
                    "param": "PageIndex",
                    "start_page": 0
                })
        
        elif "Özelgeler" in TARAMA_MODU:
            for yil in range(2025, 2014, -1):
                gorevler.append({
                    "base_url": f"https://www.verginet.net/dtt/Ozelgeler.aspx?Yil={yil}",
                    "etiket": f"Özelge {yil}",
                    "paginated": True,
                    "param": "PageIndex",
                    "start_page": 0
                })
        
        elif "KPMG - Duyurular" in TARAMA_MODU:
             gorevler.append({
                 "base_url": "https://kpmgvergi.com/yayinlar/mali-bultenler?category=duyurular&categoryId=5", 
                 "etiket": "KPMG Duyurular", 
                 "paginated": True,
                 "param": "p",
                 "start_page": 1
             })
        elif "KPMG - Vergi" in TARAMA_MODU:
             gorevler.append({
                 "base_url": "https://kpmgvergi.com/yayinlar/mali-bultenler?category=vergi&categoryId=1", 
                 "etiket": "KPMG Vergi", 
                 "paginated": True,
                 "param": "p",
                 "start_page": 1
             })
        elif "KPMG - Gümrük" in TARAMA_MODU:
             gorevler.append({
                 "base_url": "https://kpmgvergi.com/yayinlar/mali-bultenler?category=gumruk&categoryId=2", 
                 "etiket": "KPMG Gümrük", 
                 "paginated": True,
                 "param": "p",
                 "start_page": 1
             })
        elif "KPMG - SGK" in TARAMA_MODU:
             gorevler.append({
                 "base_url": "https://kpmgvergi.com/yayinlar/mali-bultenler?category=sosyal-guvenlik&categoryId=3", 
                 "etiket": "KPMG SGK", 
                 "paginated": True,
                 "param": "p",
                 "start_page": 1
             })
        
        elif "Temel Vergi Kanunları" in TARAMA_MODU:
            gorevler.append({"url": "https://www.verginet.net/dtt/7/TemelVergiKanunlari_4.aspx", "etiket": "Temel Kanun", "paginated": False, "is_kanun": True})
        elif "Diğer Vergi Kanunları" in TARAMA_MODU:
            gorevler.append({"url": "https://www.verginet.net/dtt/7/DigerVergiKanunlari_6.aspx", "etiket": "Diğer Kanun", "paginated": False, "is_kanun": True})
        elif "Vergi Yargısı" in TARAMA_MODU:
            gorevler.append({"url": "https://www.verginet.net/dtt/7/VergiYargisiMevzuati_7.aspx", "etiket": "Vergi Yargısı", "paginated": False, "is_kanun": True})
        elif "Gerekçeli" in TARAMA_MODU:
            gorevler.append({"url": "https://www.verginet.net/dtt/7/GerekceliVergiKanunlari_8.aspx", "etiket": "Gerekçeli Kanun", "paginated": False, "is_kanun": True})
        elif "Çifte Vergilendirme" in TARAMA_MODU:
            gorevler.append({"url": "https://www.verginet.net/dtt/7/CifteVergilendirmeyiOnlemeAnlasmalari_9.aspx", "etiket": "Çifte Vergi Anlaşması", "paginated": False, "is_kanun": True})
        else: 
            custom_url = st.session_state.get('custom_url_input', "https://www.verginet.net")
            gorevler.append({"url": custom_url, "etiket": "Özel URL", "paginated": False})

        total_tasks = len(gorevler)
        for task_idx, task in enumerate(gorevler):
            
            is_paginated = task.get("paginated")
            start_page = task.get("start_page", 0)
            end_page = start_page + MAX_SAYFA_LIMITI if is_paginated else start_page + 1
            
            for page_num in range(start_page, end_page):
                
                if is_paginated:
                    sep = "&" if "?" in task["base_url"] else "?"
                    param_name = task.get("param", "PageIndex")
                    page_url = f"{task['base_url']}{sep}{param_name}={page_num}"
                    current_label = f"{task['etiket']} - S.{page_num}"
                else:
                    page_url = task["url"]
                    current_label = task["etiket"]
                
                status_box.info(f"📂 [{task_idx+1}/{total_tasks}] Liste Taranıyor: {current_label}")
                driver.get(page_url)
                time.sleep(3)
                
                detay_linkleri = []
                try:
                    xpath_query = "//*[contains(@id, 'DGSirkulerler')]" if "verginet" in page_url and ("Özelge" in current_label or "Sirküler" in current_label) else "//*[contains(@id, 'pnlicerik')]"
                    
                    try:
                        container = driver.find_element(By.XPATH, xpath_query)
                    except:
                        container = driver.find_element(By.TAG_NAME, "body")

                    linkler = container.find_elements(By.TAG_NAME, "a")
                    
                    for link in linkler:
                        try:
                            txt = link.text.strip()
                            href = link.get_attribute('href')
                            
                            if txt and href and "javascript" not in href:
                                full_url = urljoin(page_url, href)
                                
                                if "verginet" in page_url:
                                    if "/dtt/" in full_url and full_url != page_url:
                                        detay_linkleri.append((txt, full_url))
                                elif "kpmg" in page_url:
                                    if full_url != page_url and len(txt) > 10 and "category" not in full_url:
                                        detay_linkleri.append((txt, full_url))
                                elif full_url != page_url:
                                    detay_linkleri.append((txt, full_url))
                        except: continue
                    
                    detay_linkleri = list(set(detay_linkleri))
                    
                except Exception as e:
                    pass 

                if not detay_linkleri:
                    if is_paginated:
                        st.info(f"⏹️ {task['etiket']} tamamlandı (Sayfa {page_num} boş/yok). Diğer göreve geçiliyor.")
                        break 
                    else:
                        st.warning(f"{current_label} sayfasında link bulunamadı.")
                        continue 
                
                st.toast(f"{current_label}: {len(detay_linkleri)} içerik bulundu.")
                
                p_bar = st.progress(0)
                for i, (baslik, url) in enumerate(detay_linkleri):
                    p_bar.progress((i + 1) / len(detay_linkleri))
                    
                    # 1. URL Kontrolü (Kesin Eşleşme)
                    if any(d['url'] == url for d in veri_listesi):
                        continue

                    # 2. Başlık Benzerlik Kontrolü (Fuzzy Deduplication)
                    # Farklı sitelerden aynı içerik gelebilir, başlıklar %90 benzerse atla.
                    is_duplicate = False
                    for item in veri_listesi:
                        mevcut_baslik = item.get('baslik', '')
                        if mevcut_baslik:
                             # Benzerlik oranı 0.85 (%85) üzerindeyse aynı sayılır
                            if difflib.SequenceMatcher(None, baslik.lower(), mevcut_baslik.lower()).ratio() > 0.85:
                                is_duplicate = True
                                break
                    
                    if is_duplicate:
                        # İsterseniz burada kullanıcıya atlandığını bildirebilirsiniz
                        # st.toast(f"Benzer içerik atlandı: {baslik}") 
                        continue

                    status_box.text(f"🔍 İşleniyor ({current_label}): {baslik[:50]}...")
                    
                    try:
                        driver.get(url)
                        time.sleep(1.5)
                        
                        if task.get("is_kanun"):
                            try:
                                tum_kanun_link = driver.find_element(By.PARTIAL_LINK_TEXT, "Tüm Kanun")
                                if tum_kanun_link:
                                    yeni_url = tum_kanun_link.get_attribute('href')
                                    driver.get(yeni_url)
                                    time.sleep(2)
                                    url = yeni_url 
                            except:
                                try:
                                    tam_metin = driver.find_element(By.PARTIAL_LINK_TEXT, "Tam Metin")
                                    yeni_url = tam_metin.get_attribute('href')
                                    driver.get(yeni_url)
                                    time.sleep(2)
                                    url = yeni_url
                                except: pass 

                        icerik = extract_content_smart(driver, is_kanun=task.get("is_kanun", False))
                        
                        if len(icerik) > 300: 
                            yeni_kayit = {
                                "id": str(uuid.uuid4()),
                                "kategori": current_label,
                                "baslik": baslik,
                                "icerik": icerik,
                                "url": url,
                                "tarih": datetime.now().strftime("%Y-%m-%d %H:%M")
                            }
                            
                            veri_listesi.append(yeni_kayit)
                            with open("verginet_data.json", "w", encoding="utf-8") as f:
                                json.dump(veri_listesi, f, ensure_ascii=False, indent=4)
                            
                    except: continue
                
                p_bar.empty()

        driver.quit()
        status_box.success(f"✅ İŞLEM TAMAM! Toplam {len(veri_listesi)} kayıt arşivde.")
        return veri_listesi
    
    except Exception as e:
        if driver: driver.quit()
        st.error(f"Kritik Hata: {e}")
        return veri_listesi

# --- 2. YAPAY ZEKA CEVAPLAYICI ---
def yapay_zekaya_sor(soru, context_data, chat_history):
    if not api_key: return "⚠️ API Anahtarı eksik."
    active_model = get_best_model()
    if not active_model: return "❌ Model hatası."

    gecmis = ""
    for msg in chat_history[:-1]: 
        gecmis += f"{'Kullanıcı' if msg['role']=='user' else 'Asistan'}: {msg['content']}\n"

    alakali_metin = ""
    soru_kelimeleri = soru.lower().split()
    bulunanlar = []
    
    for item in context_data:
        puan = 0
        baslik = item['baslik'].lower()
        icerik = item['icerik'].lower()
        
        if soru.lower() in baslik: puan += 500
        
        matched = 0
        for k in soru_kelimeleri:
            if k in baslik: matched += 1
        if matched > 0: puan += matched * 50
        
        if any(k in icerik for k in soru_kelimeleri): puan += 10
        if puan > 0: bulunanlar.append((puan, item))
    
    bulunanlar.sort(key=lambda x: x[0], reverse=True)
    
    retry_strategies = [(400000, 5), (200000, 3), (50000, 2), (20000, 1)]
    max_retries = 4
    wait_time = 2 
    model = genai.GenerativeModel(active_model)
    last_error = ""
    status_placeholder = st.empty()

    for attempt, (char_limit, doc_count) in enumerate(retry_strategies):
        
        alakali_metin = ""
        current_docs = bulunanlar[:doc_count]
        
        if not current_docs: return "İlgili bilgi bulunamadı.", []

        for score, item in current_docs:
            temiz_metin = item['icerik'].strip()
            alakali_metin += f"\n--- KAYNAK: {item['baslik']} ({item.get('kategori', '-')}) ---\n{temiz_metin[:char_limit]}\n"

        prompt = f"""
        Sen uzman bir Vergi Hukukçusu ve Müşavir Asistanısın.
        GEÇMİŞ SOHBET: {gecmis}
        KAYNAKLAR: {alakali_metin}
        SORU: {soru}
        TALİMAT: Soruyu yukarıdaki KAYNAKLAR bölümündeki bilgilere dayanarak detaylıca cevapla.
        """

        try:
            status_placeholder.caption(f"🤖 Yapay Zeka Düşünüyor... (Model: {active_model}, Veri: {char_limit} krktr)")
            response = model.generate_content(prompt)
            status_placeholder.empty()
            
            kaynak_listesi = [f"**{doc_item['baslik']}** (Skor: {score})" for score, doc_item in current_docs]
            return response.text, kaynak_listesi
            
        except Exception as e:
            err_msg = str(e)
            last_error = err_msg
            if "429" in err_msg or "Quota" in err_msg:
                status_placeholder.warning(f"⚠️ Anlık Yoğunluk (Retry)...")
                time.sleep(wait_time)
                wait_time += 2 
                continue
            else:
                status_placeholder.empty()
                return f"❌ Hata: {err_msg}", []
                
    return f"❌ İşlem tamamlanamadı.\nSon Hata: {last_error}", []

# --- ARAYÜZ ---
if 'veriler' not in st.session_state:
    if os.path.exists("verginet_data.json"):
        with open("verginet_data.json", "r", encoding="utf-8") as f:
            st.session_state.veriler = json.load(f)
    else:
        st.session_state.veriler = []

if 'messages' not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Merhaba! Vergi mevzuatını taramaya hazırım."}]

if TARAMA_MODU == "Tekil URL Tarama (Manuel)":
    st.sidebar.text_input("Taranacak URL", "https://www.verginet.net", key="custom_url_input")

if api_key:
    best_model = get_best_model()
    if best_model:
        st.sidebar.success(f"✅ Aktif Model: {best_model}")

if st.sidebar.button(f"🚀 {TARAMA_MODU.split('(')[0]} TARAMASINI BAŞLAT"):
    st.session_state.veriler = taramayi_baslat()
    st.rerun()

col1, col2 = st.columns([3, 1])
with col1:
    if st.session_state.veriler:
        st.success(f"📚 {len(st.session_state.veriler)} Kayıt Hafızada.")
    else:
        st.info("Veri yok. Sol menüden taramayı başlatın.")

with col2:
    if st.session_state.veriler:
        st.download_button("💾 Yedekle", data=json.dumps(st.session_state.veriler, ensure_ascii=False), file_name="mevzuat_arsivi.json")

st.divider()

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

if prompt := st.chat_input("Sorunuzu yazın..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)
    
    if st.session_state.veriler:
        with st.spinner("Analiz ediliyor..."):
            cevap, kaynaklar = yapay_zekaya_sor(prompt, st.session_state.veriler, st.session_state.messages)
            
            st.session_state.messages.append({"role": "assistant", "content": cevap})
            st.chat_message("assistant").write(cevap)
            
            if kaynaklar:
                with st.expander("🔍 Kaynaklar"):
                    for k in kaynaklar: st.markdown(f"- {k}")
    else:
        st.error("Önce verileri çekmelisiniz.")