import streamlit as st
import json
import google.generativeai as genai
import re
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# --- AYARLAR ---
GOOGLE_API_KEY = "AIzaSyBAZj52dZxz6qQOpu9Ds3EJm5FlErWeL3A" # <-- ANAHTARINI BURAYA YAPIŞTIR!
ACTIVE_MODEL_NAME = 'gemini-2.5-flash'

# --- SİSTEM TALİMATI ---
SYSTEM_INSTRUCTION = """
Sen Türkiye vergi mevzuatına hakim, kıdemli bir Mali Müşavir Asistanısın. 
Görevin: Sana verilen kaynakları kullanarak kullanıcıyla SOHBET ETMEK ve sorularını yanıtlamaktır.

KURALLAR:
1. **Sohbet Et:** Robotik cevaplar verme. Kullanıcının sorusundaki nüansı yakala.
2. **Kaynağı Metne Göm:** Cevabını dayandırdığın Kanun, Tebliğ veya Sirküler ismini cevabın içinde cümle arasında geçir.
3. **TARİH DETAYI:** Kullandığın kaynağın içinde veya başlığında bir TARİH (Yıl, Resmi Gazete Tarihi vb.) görüyorsan, bunu MUTLAKA kaynağın isminin yanına parantez içinde ekle.
4. **Listeyi Gizle:** Cevabın sonuna "Kaynaklar" diye bir liste ekleme.
5. **Dürüst Ol:** Kaynaklarda bilgi yoksa "Bu detay sağlanan metinlerde yer almıyor" de.
6. **İLTİFAT:** İnsani tepkilere kibarca, profesyonelce karşılık ver.
"""

st.set_page_config(page_title="MüşavirGPT", page_icon="⚖️", layout="centered")

# --- CSS ANİMASYONU (NOKTA NOKTA BELİRME EFEKTİ) ---
st.markdown("""
<style>
@keyframes dot-keyframes {
  0% { content: '.'; }
  33% { content: '..'; }
  66% { content: '...'; }
  100% { content: ''; }
}
.loading-text::after {
  content: '.';
  animation: dot-keyframes 1.5s infinite step-start;
  display: inline-block;
  width: 1.5em;
  text-align: left;
}
.loading-text {
    font-size: 1.1em;
    color: #555;
    font-weight: 500;
    font-style: italic;
}
</style>
""", unsafe_allow_html=True)

def kurulum_yap():
    if "AIza" not in GOOGLE_API_KEY or GOOGLE_API_KEY == "AIza...":
        st.error("⚠️ API Key eksik! Lütfen app.py dosyasını düzenleyin.")
        st.stop()
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        return genai.GenerativeModel(ACTIVE_MODEL_NAME, system_instruction=SYSTEM_INSTRUCTION)
    except Exception as e:
        st.error(f"Hata: {e}")
        st.stop()

def veri_yukle():
    try:
        with open("musavirgpt_veri_seti.json", "r", encoding="utf-8") as f: return json.load(f)
    except: st.error("Veri seti bulunamadı."); st.stop()

def en_alakali_metinleri_getir(soru, veriler, limit=15):
    soru_kelimeleri = set(re.findall(r'\b\w+\b', soru.lower()))
    skorlu = []
    for v in veriler:
        metin = (str(v.get('baslik', '')) + " " + str(v.get('icerik', ''))).lower()
        metin_kelimeleri = set(re.findall(r'\b\w+\b', metin))
        skor = len(soru_kelimeleri.intersection(metin_kelimeleri))
        if skor >= 3: skorlu.append((skor, v))
    skorlu.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in skorlu[:limit]]

model = kurulum_yap()
veriler = veri_yukle()

st.title("⚖️ MüşavirGPT")
st.caption("Yapay Zeka Destekli Mevzuat Asistanı")

if "chat_session" not in st.session_state:
    st.session_state.chat_session = model.start_chat(history=[])

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

if prompt := st.chat_input("Sorunuzu yazın..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        # 1. Spinner Yerine Özel Animasyonlu Alan Oluşturuyoruz
        bilgi_kutusu = st.empty()
        bilgi_kutusu.markdown('<p class="loading-text">Yazıyor</p>', unsafe_allow_html=True)
        
        # İşlemler Başlıyor
        alakali_kayitlar = en_alakali_metinleri_getir(prompt, veriler)
        
        context_text = ""
        for i, v in enumerate(alakali_kayitlar):
            raw_baslik = v.get('baslik', '')
            temiz_baslik = re.sub(r'\s*\((Parça|Bölüm)\s*\d+\)', '', raw_baslik).strip()
            suni_kanun_adi = "Resmi Mevzuat Belgesi"
            context_text += f"\n--- KAYNAK {i+1} ---\nBaşlık: {temiz_baslik}\nTür: {suni_kanun_adi}\nİçerik: {v.get('icerik')}\n"
        
        full_prompt = (
            f"KAYNAKLAR (Eğer soru teknikse kullan, yoksa dikkate alma):\n{context_text}\n\n"
            f"KULLANICI MESAJI: {prompt}\n\n"
            f"Lütfen 'Müşavir Asistanı' kimliğinle cevapla."
        )
        
        try:
            resp = st.session_state.chat_session.send_message(full_prompt)
            cevap = resp.text 
        except Exception as e: cevap = f"Hata: {e}"

        # 2. İşlem Bitince Animasyonlu Yazıyı Siliyoruz
        bilgi_kutusu.empty()

        st.markdown(cevap)
        st.session_state.messages.append({"role": "assistant", "content": cevap})