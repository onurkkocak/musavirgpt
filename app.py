import streamlit as st
import os
import json
import time
import pandas as pd
import google.generativeai as genai
from datetime import datetime
import uuid
import re
import string 
import requests 
import io 
import pdfplumber 
import base64 # Base64 çözme için eklendi

# Firebase
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from google.api_core.exceptions import PermissionDenied, ResourceExhausted, NotFound, ServiceUnavailable

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="MüşavirGPT Enterprise", page_icon="☁️", layout="wide")

# --- AYARLAR ---
ADMIN_SIFRESI = "admin123" 
FIREBASE_KEY_PATH = "firestore_key.json"
DEFAULT_PDF_KLASORU = "indirilen_pdfler" 

# TÜRMOB SCRAPER AYARLARI
BASE_URL = "https://www.turmob.org.tr"
START_URL = "https://www.turmob.org.tr/ekutuphane/e2f9f8fd-af81-456b-8626-2e938f66dd45/mevzuat-sirkuleri/1"
TARANACAK_YIL_ADEDI = 10 
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# --- 1. FIREBASE BAĞLANTISI ---
@st.cache_resource
def db_baglan():
    try:
        if not firebase_admin._apps:
            if os.path.exists(FIREBASE_KEY_PATH):
                # Local test için
                cred = credentials.Certificate(FIREBASE_KEY_PATH)
                firebase_admin.initialize_app(cred)
            elif "firestore" in st.secrets and "base64_key" in st.secrets["firestore"]:
                # Cloud ortamı için Base64 çözümü
                try:
                    # 1. Base64 dizesini çek
                    base64_encoded_key = st.secrets["firestore"]["base64_key"]
                    
                    # 2. Base64'ten JSON metnine çöz
                    json_bytes = base64.b64decode(base64_encoded_key)
                    json_string = json_bytes.decode('utf-8')
                    
                    # 3. JSON metnini sözlüğe çevir ve Firebase'i başlat
                    key_dict = json.loads(json_string)
                    cred = credentials.Certificate(key_dict)
                    firebase_admin.initialize_app(cred)
                except Exception as e:
                    # JSON, Base64 veya Firebase başlatma hatası varsa
                    print(f"KRİTİK BASE64/JSON HATA: {e}")
                    return None
            else:
                # Anahtar bulunamadı
                return None
        return firestore.client()
    except Exception as e:
        print(f"DB Başlatma Hatası: {e}")
        return None

db = db_baglan()

def db_kontrol():
    if not db:
        # Hata mesajı güncellendi: Kullanıcıyı secrets.toml'a yönlendirir.
        st.error(f"❌ Veritabanı bağlantısı kurulamadı. Lütfen 'secrets.toml' dosyanızdaki Firebase anahtarını kontrol edin.")
        return False
    try:
        # DB bağlantısını basit bir okuma ile test et
        db.collection('test').limit(1).get()
        return True
    except PermissionDenied:
        st.error("🚨 Yetki Hatası (403): Google Cloud'da API aktif değil!")
        return False
    except Exception as e:
        st.error(f"Veritabanı Hatası: {e}")
        return False

# --- 2. VERİ OKUMA VE YAZMA OPERASYONLARI ---
def oneri_ekle(bilgi, kaynak="Kullanıcı"):
    if not db: return False
    try:
        docs = db.collection('bilgiler').where('bilgi', '==', bilgi).stream()
        for doc in docs: return False 
        veri = {
            "id": str(uuid.uuid4()), "bilgi": bilgi, "kaynak": kaynak,
            "tarih": datetime.now().strftime("%Y-%m-%d %H:%M"), "durum": "beklemede"
        }
        db.collection('bilgiler').document(veri['id']).set(veri)
        return True
    except: return False

def onayli_bilgileri_getir():
    if not db: return []
    try:
        docs = db.collection('bilgiler').where('durum', '==', 'onaylı').stream()
        return [doc.to_dict()['bilgi'] for doc in docs]
    except: return []

def bekleyen_onerileri_getir():
    if not db: return []
    try:
        docs = db.collection('bilgiler').where('durum', '==', 'beklemede').stream()
        return [doc.to_dict() for doc in docs]
    except: return []

def durum_guncelle(koleksiyon, doc_id, yeni_durum):
    if not db: return
    try:
        doc_ref = db.collection(koleksiyon).document(doc_id)
        if yeni_durum == 'sil': doc_ref.delete()
        else: doc_ref.update({"durum": yeni_durum})
    except: pass

def log_ekle(islem, mesaj):
    if not db: return
    try:
        veri = {
            "id": str(uuid.uuid4()), "islem": islem, "mesaj": mesaj,
            "tarih": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        db.collection('sistem_loglari').document(veri['id']).set(veri)
    except: pass

def loglari_getir(limit=5):
    if not db: return []
    try:
        docs = db.collection('sistem_loglari').order_by('tarih', direction=firestore.Query.DESCENDING).limit(limit).stream()
        return [doc.to_dict() for doc in docs]
    except: return []

@st.cache_data(ttl=3600)
def sirkulerleri_getir():
    """Tüm sirkülerleri Firebase'den çeker ve önbelleğe alır."""
    if not db: return []
    try:
        docs = db.collection('sirkulerler').stream()
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        if "403" in str(e): st.error("Veritabanı İzni Yok")
        return []

def sirkulerleri_temizle():
    if not db: return False
    try:
        docs = db.collection('sirkulerler').stream()
        count = 0
        for doc in docs:
            doc.reference.delete()
            count += 1
        return count
    except Exception as e:
        st.error(f"Silme Hatası: {e}")
        return 0

# --- 3. GEMINI AI MOTORU (GÜNCEL) ---

def configure_gemini():
    api_key = None
    try:
        if "GOOGLE_API_KEY" in st.secrets: api_key = st.secrets["GOOGLE_API_KEY"]
    except: pass
    if not api_key:
        with st.sidebar:
            api_key = st.text_input("Google API Key", type="password")
    if api_key:
        genai.configure(api_key=api_key)
        return True
    return False

def get_working_models():
    """SİZİN HESABINIZDAKİ AKTİF MODELLERE GÖRE AYARLANDI."""
    priority_models = [
        'models/gemini-2.5-flash',
        'models/gemini-2.0-flash',
        'models/gemini-1.5-flash-latest',
        'models/gemini-1.5-pro-latest'
    ]
    return priority_models

def debug_available_models():
    try:
        ms = genai.list_models()
        names = [m.name for m in ms if 'generateContent' in m.supported_generation_methods]
        return names
    except Exception as e:
        return [f"Model listesi alınamadı: {e}"]

def generate_with_fallback(prompt_parts):
    model_list = get_working_models()
    last_error = None
    
    for model_name in model_list:
        try:
            model = genai.GenerativeModel(model_name)
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    response = model.generate_content(prompt_parts)
                    if response and response.text:
                        return response.text
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "Quota" in err_str or "ResourceExhausted" in err_str:
                        time.sleep(3 * (attempt + 1))
                        continue 
                    else:
                        raise e 
            
        except Exception as e:
            last_error = str(e)
            continue 

    available = debug_available_models()
    log_ekle("KRİTİK AI HATASI", f"Son hata: {last_error}. Açık Modeller: {available}")
    
    return f"⚠️ Servis şu an yanıt veremiyor.\n\nTeknik Detay: Kullandığınız API Anahtarı mevcut modellerimizle uyuşmuyor olabilir.\nErişilebilir Modeller: {available}\nSon Hata: {last_error}"

def pdf_sayfasini_gorsel_oku(image_bytes):
    # Bu fonksiyon chat odaklı modda devre dışıdır.
    prompt = "PDF'in görselini analiz et."
    return generate_with_fallback(prompt)


# --- YÖNETİCİ MODU FONKSİYONLARI (Pasif/Placeholder) ---
def vision_ile_tara_ve_yukle_yerel(pdf_klasoru):
    st.error("Bu fonksiyon Cloud ortamında devre dışıdır (Yerel disk okuması gerektirir).")
    return False, 0 

def otopilot_tum_arsiv():
    st.error("Bu fonksiyon Cloud ortamında devre dışıdır (Web taraması gerektirir).")
    return False, 0


# --- 5. CEVAPLAMA MOTORU ---
def get_gemini_response(question, context, chat_history):
    formatted = ""
    for msg in chat_history[-5:]:
        r = "Kullanıcı" if msg["role"]=="user" else "Asistan"
        formatted += f"{r}: {msg['content']}\n"
    
    prompt = f"""
    Sen Uzman Mali Müşavir Asistanısın. Görevin sadece VERİLER (Sirkülerler) kısmındaki bilgileri esas alarak soruyu cevaplamaktır.
    
    VERİLER: {context}
    GEÇMİŞ: {formatted}
    SORU: {question}
    
    KRİTİK TALİMAT: Veri tablosu varsa, oradaki rakamları kullanarak net ve kesin cevap ver. Cevabın TÜRKÇE olmalıdır.
    """
    
    return generate_with_fallback(prompt)

# --- ARAYÜZ (MAIN) ---
def main():
    st.markdown("<h1 style='text-align: center;'>☁️ MüşavirGPT Enterprise</h1>", unsafe_allow_html=True)
    if not db_kontrol(): return
    
    configure_gemini()
    
    # Veriyi çek (Önbelleğe alınmış olanı kullan)
    data = sirkulerleri_getir()
    
    with st.sidebar:
        st.header("🔒 Yönetici")
        # Yönetici girişi
        if st.session_state.get('admin_logged', False) or st.text_input("Şifre", type="password", key='admin_pass') == ADMIN_SIFRESI:
            st.session_state.admin_logged = True
            st.success("Giriş Yapıldı")
            
            # YÖNETİCİ OPERASYONLARI
            st.markdown("### Operasyonlar")
            
            # 1. YEREL YÜKLEME BUTONU (Pasif)
            if st.button(f"1. İndirilen Klasörünü İşle (Vision)"):
                 with st.spinner("İşleniyor..."):
                    ok, n = vision_ile_tara_ve_yukle_yerel(DEFAULT_PDF_KLASORU)
            
            # 2. WEB TARAMA BUTONU (Pasif)
            if st.button(f"2. Web Tarama (PDFplumber)"):
                with st.spinner("İşleniyor..."):
                    ok, n = otopilot_tum_arsiv()
            
            # 3. TEMİZLEME BUTONU
            if st.button("3. Firebase'i Temizle (DİKKAT!)"):
                with st.spinner("Tüm sirkülerler siliniyor..."):
                    count = sirkulerleri_temizle()
                    st.warning(f"Toplam {count} sirküler silindi.")
                    st.cache_data.clear()
                    st.rerun() # Temizlik sonrası uygulamayı yenile
            
            st.divider()
            
            # Loglar ve Teşhis
            loglar = loglari_getir(5)
            with st.expander("Loglar"):
                for l in loglar: st.caption(f"{l['tarih']} - {l['mesaj']}")
        else:
            st.caption("Girmek için şifreyi giriniz.")


    # Chat Arayüzü
    if not data: st.warning("Veritabanı boş. Yönetici panelinden yükleme yapın.")
    else:
        df = pd.DataFrame(data)
        st.caption(f"Aktif Belge Sayısı: {len(df)}")

        if "messages" not in st.session_state:
            st.session_state.messages = [{"role":"assistant", "content":"Buyurun, yardımcı olayım."}]
            
        for msg in st.session_state.messages:
            st.chat_message(msg["role"]).markdown(msg["content"])
            
        if p := st.chat_input("Sorunuz..."):
            st.session_state.messages.append({"role":"user", "content":p})
            st.chat_message("user").markdown(p)
            
            with st.spinner("Araştırılıyor..."):
                # --- ARAMA VE CONTEXT OLUŞTURMA ---
                p_clean = p.translate(str.maketrans('', '', string.punctuation)).lower()
                kws = p_clean.split()
                
                docs = []
                for _, r in df.iterrows():
                    # Basit anahtar kelime eşleştirme
                    if any(k in r['icerik'].lower() for k in kws):
                        docs.append((r['baslik'], r['icerik']))
                
                ctx = ""
                # En alakalı ilk 3 belgeyi contexte ekle
                for t, c in docs[:3]: 
                    ctx += f"\n--- {t} ---\n{c[:50000]}\n" # 50000 karakterlik limit
                
                # Cevap üretme
                res = get_gemini_response(p, ctx, st.session_state.messages)
                
            st.session_state.messages.append({"role":"assistant", "content":res})
            st.chat_message("assistant").markdown(res)

if __name__ == "__main__":
    if 'admin_logged' not in st.session_state:
         st.session_state.admin_logged = False
    main()