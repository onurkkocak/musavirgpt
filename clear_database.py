import os
import time

def veritabanini_temizle():
    DOSYA_ADI = "musavirgpt_veri_seti.json"
    
    print(f"🧨 UYARI: {DOSYA_ADI} dosyası kalıcı olarak silinecektir.")
    time.sleep(1)
    
    if os.path.exists(DOSYA_ADI):
        os.remove(DOSYA_ADI)
        print("✅ ESKİ VERİTABANI BAŞARIYLA SİLİNDİ.")
    else:
        print("ℹ️ Veritabanı dosyası zaten bulunamadı.")
        
    print("🚀 Veritabanı temiz. Yüklemeye hazırsınız.")

if __name__ == "__main__":
    veritabanini_temizle()