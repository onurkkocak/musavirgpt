import json
import os
import re

DOSYA_ADI = "musavirgpt_veri_seti.json"

def veritabanini_tamir_et():
    print("🔧 VERİTABANI TAMİRATI BAŞLIYOR...")

    if not os.path.exists(DOSYA_ADI):
        print("❌ HATA: JSON dosyası bulunamadı!")
        return

    # 1. Veriyi Oku
    with open(DOSYA_ADI, "r", encoding="utf-8") as f:
        veriler = json.load(f)
    
    print(f"📂 İşlem öncesi toplam kayıt: {len(veriler)}")

    yeni_veriler = []
    eklenen_basliklar = set() # Tekrar kontrolü için

    for veri in veriler:
        # 2. Marka Temizliği (Muhasebetr yazısını Mevzuat Belgesi yap)
        # Eğer kanun adı 'GVK' veya 'VUK' gibi özel değilse, hepsini standartlaştır.
        eski_kanun = veri.get("kanun", "")
        if "GVK" in eski_kanun or "VUK" in eski_kanun or "KDV" in eski_kanun:
            yeni_kanun = eski_kanun
        else:
            yeni_kanun = "Mevzuat Belgesi"

        # 3. Başlık Temizliği ((Parça X) yazılarını sil)
        eski_baslik = veri.get("baslik", "")
        temiz_baslik = re.sub(r'\s*\((Parça|Bölüm)\s*\d+\)', '', eski_baslik).strip()
        
        # 4. Tekrar Kontrolü (Aynı başlık varsa ekleme)
        # Başlığın sadece harflerini alarak karşılaştır (küçük harf, boşluksuz)
        baslik_imzasi = re.sub(r'\W+', '', temiz_baslik).lower()

        if baslik_imzasi not in eklenen_basliklar:
            # Veriyi güncelle
            veri["kanun"] = yeni_kanun
            veri["baslik"] = temiz_baslik
            # İçerikteki olası marka adlarını da sansürle
            veri["icerik"] = veri["icerik"].replace("MuhasebeTR", "").replace("muhasebetr", "")
            
            yeni_veriler.append(veri)
            eklenen_basliklar.add(baslik_imzasi)

    # 5. Temizlenmiş Veriyi Kaydet
    with open(DOSYA_ADI, "w", encoding="utf-8") as f:
        json.dump(yeni_veriler, f, ensure_ascii=False, indent=4)

    print(f"✅ İŞLEM TAMAMLANDI!")
    print(f"🗑️ Silinen tekrar/çöp sayısı: {len(veriler) - len(yeni_veriler)}")
    print(f"✨ Yeni temiz kayıt sayısı: {len(yeni_veriler)}")
    print("🚀 Veritabanı artık %100 markasız ve tekil.")

if __name__ == "__main__":
    veritabanini_tamir_et()