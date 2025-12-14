import json
import os
import time

def get_sample_data():
    """Garantili çalışır test verilerini döndürür."""
    # Bu metinler en başta başarılı olan GVK had ve tutarlar, KDV, KKM gibi test verileridir.
    return [
        {"id": "GVK-HAD-TUTAR", "kanun": "193 GVK/VUK", "baslik": "Yeniden Değerleme Oranında Artırılan Had ve Tutarlar", "icerik": "Gelir Vergisi Kanununun mükerrer 123 üncü maddesinin (2) numaralı fıkrasında, Kanunun 21, 23/8, 31, 47, 48, mükerrer 80, 82 ve 86 ncı maddelerinde yer alan maktu had ve tutarların, her yıl bir önceki yıla ilişkin olarak Vergi Usul Kanunu hükümlerine göre belirlenen yeniden değerleme oranında artırılmak suretiyle uygulanacağı, bu şekilde hesaplanan maktu had ve tutarların %5’ini aşmayan kesirlerin dikkate alınmayacağı, Bakanlar Kurulunun, bu suretle tespit edilen had ve tutarları yarısına kadar artırmaya veya indirmeye yetkili olduğu hükmü yer almaktadır. Aynı maddenin (3) numaralı fıkrasında da 103 üncü maddede yer alan vergi tarifesinin gelir dilimi tutarları hakkında da yukarıdaki hükmün uygulanacağı öngörülmüştür. Bu hüküm göz önüne alınarak Gelir Vergisi Kanununun 2, 23/8, 31, 47, 48, mükerrer 80, 82, 86 ve 103 üncü maddelerinde yer alıp 2014 yılında uygulanan had ve tutarların 2014 yılı için %10,11 (on virgül on bir) olarak tespit edilen yeniden değerleme oranında artırılması suretiyle belirlenen ve 2015 takvim yılında uygulanacak olan had ve tutarlar aşağıda şekilde tespit edilmiştir."},
        {"id": "KDV-TEVKIFAT", "kanun": "3065 KDV", "baslik": "Temizlik Hizmetinde KDV Tevkifat Oranı", "icerik": "KDV Genel Uygulama Tebliğine göre, temizlik, çevre ve bahçe bakım hizmetleri alıcıları tarafından KDV'nin (10/10) oranında tevkifata tabi tutulması gerekmektedir. Ancak bu oran sadece kamu kurumları, bankalar, döner sermayeli kuruluşlar ve sigorta şirketleri gibi belirlenmiş KDV mükellefleri için geçerlidir. Tevkifat yükümlülüğü tam tevkifat olarak uygulanmaktadır."},
        {"id": "VUK-ENFLASYON", "kanun": "213 VUK", "baslik": "Enflasyon Düzeltmesi Zorunluluğu 2025", "icerik": "Vergi Usul Kanunu'na göre, Türkiye İstatistik Kurumu tarafından ilan edilen Yİ-ÜFE'nin son üç hesap döneminde %100'den ve içinde bulunulan hesap döneminde %10'dan fazla olması durumunda, işletmelerin bilançolarında yer alan parasal olmayan kıymetlerini enflasyon düzeltmesine tabi tutmaları zorunludur. Düzeltme işlemi, bilançoda yer alan parasal olmayan kıymetlerin enflasyon düzeltme katsayısı ile çarpılması suretiyle yapılır."},
        {"id": "KVK-KKM", "kanun": "5520 KVK", "baslik": "Kurumlar Vergisi Kanunu Kur Korumalı Mevduat İstisnası", "icerik": "Kurumlar Vergisi Kanunu'na göre, Kur Korumalı Mevduat (KKM) hesaplarından elde edilen kur farkı gelirleri, belirli süreler dahilinde kurumlar vergisinden istisnadır. Bu istisnadan yararlanılabilmesi için hesapların ilgili bankalar nezdinde açılmış olması ve belirli vadelerde tutulması şarttır."},
    ]

def initialize_database():
    DOSYA_ADI = "musavirgpt_veri_seti.json"
    
    # JSON'u silmek yerine, sadece data initializer verisini yazdırırız
    data = get_sample_data()
    
    with open(DOSYA_ADI, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        
    print("------------------------------------------------")
    print("✅ KRİTİK VERİ ARŞİVİ YÜKLENDİ (Garantili Çalışır Metinler).")
    print(f"📊 Toplam Kayıt Sayısı: {len(data)}")
    print("🚀 Artık Yapay Zeka Testine Hazırız.")

if __name__ == "__main__":
    initialize_database()