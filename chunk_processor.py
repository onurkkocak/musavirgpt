import os
import json
import hashlib
import re

# --- AYARLAR ---
KAYNAK_KLASOR = "muhasebetr_arsivi" 
HEDEF_DB = "musavirgpt_veri_seti.json"
CHUNK_BOYUTU = 1500  
OVERLAP = 200        

def sabit_boyutlu_parcala(text, chunk_size, overlap):
    if not text: return []
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end]
        if len(chunk.strip()) > 50: chunks.append(chunk.strip())
        start += (chunk_size - overlap)
    return chunks

def process_and_load_chunks():
    print(f"🔥 VERİTABANI SIFIRLANIYOR VE YENİLENİYOR...")
    
    # 1. ESKİ VERİTABANINI ZORLA SİL (Kritik Adım)
    if os.path.exists(HEDEF_DB):
        os.remove(HEDEF_DB)
        print("🗑️ Eski hatalı veritabanı silindi.")

    if not os.path.exists(KAYNAK_KLASOR):
        print("❌ HATA: Kaynak klasör bulunamadı.")
        return

    mevcut_veriler = []
    
    # 2. GARANTİ VERİLERİ (Manuel Ekleme - Data Initializer'a gerek bırakmaz)
    # Buraya en kritik, garantili test verilerini ekliyoruz.
    garanti_veriler = [
        {"id": "TEST-GVK", "kanun": "Mevzuat Belgesi", "baslik": "Yeniden Değerleme Oranında Artırılan Had ve Tutarlar", "icerik": "Gelir Vergisi Kanununun mükerrer 123 üncü maddesinin (2) numaralı fıkrasında... yeniden değerleme oranında artırılmak suretiyle uygulanacağı..."},
        {"id": "TEST-KDV", "kanun": "Mevzuat Belgesi", "baslik": "Temizlik Hizmetinde KDV Tevkifat Oranı", "icerik": "KDV Genel Uygulama Tebliğine göre, temizlik, çevre ve bahçe bakım hizmetleri alıcıları tarafından KDV'nin (10/10) oranında tevkifata tabi tutulması gerekmektedir."}
    ]
    mevcut_veriler.extend(garanti_veriler)

    dosyalar = [f for f in os.listdir(KAYNAK_KLASOR) if f.endswith('.txt')]
    print(f"📁 {len(dosyalar)} dosya işleniyor...")

    yeni_eklenen = 0
    for dosya_adi in dosyalar:
        dosya_yolu = os.path.join(KAYNAK_KLASOR, dosya_adi)
        try:
            with open(dosya_yolu, "r", encoding="utf-8") as f:
                icerik_ham = f.read()
            
            satirlar = icerik_ham.split("\n")
            kaynak_url = ""
            baslik = dosya_adi.replace(".txt", "")
            gercek_metin_listesi = []

            for satir in satirlar:
                if satir.startswith("KAYNAK:"): kaynak_url = satir.replace("KAYNAK:", "").strip()
                elif satir.startswith("BAŞLIK:"): baslik = satir.replace("BAŞLIK:", "").strip()
                else: gercek_metin_listesi.append(satir)
            
            full_text = "\n".join(gercek_metin_listesi)
            
            # Marka Temizliği (Metin içindeki Muhasebetr yazılarını da siliyoruz)
            full_text = re.sub(r'MuhasebeTR', '', full_text, flags=re.IGNORECASE)
            
            parcalar = sabit_boyutlu_parcala(full_text, CHUNK_BOYUTU, OVERLAP)
            
            for i, parca_metni in enumerate(parcalar):
                metin_hash = hashlib.sha256(parca_metni.encode('utf-8')).hexdigest()
                yeni_kayit = {
                    "id": f"MEV-{metin_hash[:10]}",
                    "kanun": "Mevzuat Belgesi", # <-- BURASI ARTIK 'Mevzuat Belgesi' OLARAK KAYDEDİLİYOR
                    "tarih": "Güncel",
                    "baslik": f"{baslik}", 
                    "icerik": parca_metni,
                    "kaynak_url": kaynak_url,
                    "hash": metin_hash
                }
                mevcut_veriler.append(yeni_kayit)
                yeni_eklenen += 1
        except Exception as e: pass

    with open(HEDEF_DB, "w", encoding="utf-8") as f:
        json.dump(mevcut_veriler, f, ensure_ascii=False, indent=4)

    print(f"✅ İŞLEM TAMAM. {yeni_eklenen} yeni parça eklendi. Veritabanı tertemiz.")

if __name__ == "__main__":
    process_and_load_chunks()