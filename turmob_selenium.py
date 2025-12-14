from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import json
import time
import requests
import io
import pdfplumber
import pytesseract
from pdf2image import convert_from_bytes
import os
import base64
from urllib.parse import unquote

# --- AYARLAR ---
TARGET_URL = "https://www.turmob.org.tr/sirkuler/1/vergi"
OUTPUT_FILE = "musavirgpt_veri_seti.json"
TARANACAK_SAYFA_ADEDI = 2

# !!! ÖNEMLİ !!!: Tesseract ve Poppler yollarını kendi bilgisayarına göre ayarla
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
POPPLER_PATH = None 

# Tarayıcı gibi görünmek için Header bilgisi
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def ocr_ile_oku(pdf_bytes, sayfa_index):
    print(f"      👀 OCR Devreye Girdi (Sayfa {sayfa_index+1})...")
    try:
        images = convert_from_bytes(pdf_bytes, first_page=sayfa_index+1, last_page=sayfa_index+1, poppler_path=POPPLER_PATH)
        metin = ""
        for img in images:
            metin += pytesseract.image_to_string(img, lang='tur')
        return metin
    except Exception as e:
        print(f"      ⚠️ OCR Hatası: {e}")
        return ""

def tabloyu_markdown_yap(page):
    markdown_text = ""
    settings = {
        "vertical_strategy": "lines", 
        "horizontal_strategy": "lines",
        "intersection_x_tolerance": 5,
    }
    
    tables = page.extract_tables(table_settings=settings)
    if not tables:
        settings["vertical_strategy"] = "text"
        settings["horizontal_strategy"] = "text"
        tables = page.extract_tables(table_settings=settings)

    for table in tables:
        if not table: continue
        clean_table = []
        for row in table:
            clean_row = [" " if c is None else str(c).replace('\n', ' ').strip() for c in row]
            if any(cell != " " for cell in clean_row):
                clean_table.append(clean_row)
        
        if not clean_table: continue

        try:
            markdown_text += "\n\n| " + " | ".join(clean_table[0]) + " |\n"
            markdown_text += "| " + " | ".join(["---"] * len(clean_table[0])) + " |\n"
            for row in clean_table[1:]:
                markdown_text += "| " + " | ".join(row) + " |\n"
            markdown_text += "\n"
        except:
            continue

    return markdown_text

def fix_url_typos(url):
    """
    URL içindeki bilinen yazım hatalarını düzeltir.
    """
    if not url: return url
    corrections = {
        'detaailPdf': 'detay',
        'detaail': 'detay',
        'detailPdf': 'detay',
        'sirkuler//': 'sirkuler/'
    }
    for bad, good in corrections.items():
        if bad in url:
            url = url.replace(bad, good)
    return url

def download_blob(driver, blob_url):
    """
    Python requests ile indirilemeyen 'blob:' URL'lerini JavaScript enjekte ederek indirir.
    """
    print(f"      🧪 Blob İndiricisi Çalışıyor: {blob_url}")
    script = """
    var uri = arguments[0];
    var callback = arguments[1];
    var toBase64 = function(buffer){for(var r,n=new Uint8Array(buffer),t=n.length,a=new Uint8Array(4*Math.ceil(t/3)),i=new Uint8Array(64),o=0,c=0;64>c;++c)i[c]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".charCodeAt(c);for(o=0,r=0;t-t%3>o;o+=3,r+=4){var v=n[o]<<16|n[o+1]<<8|n[o+2];a[r]=i[v>>18],a[r+1]=i[v>>12&63],a[r+2]=i[v>>6&63],a[r+3]=i[63&v]}return t%3===1?(v=n[t-1],a[r]=i[v>>2],a[r+1]=i[v<<4&63],a[r+2]=61,a[r+3]=61):t%3===2&&(v=n[t-2]<<8|n[t-1],a[r]=i[v>>10],a[r+1]=i[v>>4&63],a[r+2]=i[v<<2&63],a[r+3]=61),new TextDecoder("ascii").decode(a)};
    var xhr = new XMLHttpRequest();
    xhr.responseType = 'arraybuffer';
    xhr.onload = function(){ callback(toBase64(xhr.response)) };
    xhr.onerror = function(){ callback(xhr.status) };
    xhr.open('GET', uri);
    xhr.send();
    """
    try:
        base64_result = driver.execute_async_script(script, blob_url)
        if isinstance(base64_result, int): # Hata kodu döndüyse
            print(f"      ❌ Blob İndirme Hatası (HTTP {base64_result})")
            return None
        return base64.b64decode(base64_result)
    except Exception as e:
        print(f"      ❌ Blob JS Hatası: {e}")
        return None

def verileri_guncelle():
    print("🚀 Güncelleme Başladı (V26 - BLOB DESTEKLİ PDF MODU)...")
    
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--enable-javascript") 
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.maximize_window()
    
    toplanacak_linkler = []
    
    try:
        # AŞAMA 1: LİNKLERİ TOPLA
        print("🔍 Linkler toplanıyor...")
        driver.get(TARGET_URL)
        time.sleep(3)

        for sayfa_no in range(1, TARANACAK_SAYFA_ADEDI + 1):
            kutular = driver.find_elements(By.XPATH, "//div[contains(@class, 'border-blue')]")
            for kutu in kutular:
                try:
                    link_elem = kutu.find_element(By.TAG_NAME, "a")
                    url = link_elem.get_attribute("href")
                    if url and (url not in toplanacak_linkler):
                        toplanacak_linkler.append(url)
                except: continue
            
            if sayfa_no < TARANACAK_SAYFA_ADEDI:
                try:
                    hedef_sayfa = sayfa_no + 1
                    xpath_query = f"//button[@name='currentPage' and @value='{hedef_sayfa}']"
                    buton = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, xpath_query)))
                    driver.execute_script("arguments[0].click();", buton)
                    time.sleep(3)
                except: break
        
        # AŞAMA 2: PDF ANALİZİ
        tum_veriler = []
        print(f"📦 {len(toplanacak_linkler)} sirküler inceleniyor...")
        
        for i, raw_url in enumerate(toplanacak_linkler):
            
            url = fix_url_typos(raw_url)
            print(f"\n   ⬇️ [{i+1}/{len(toplanacak_linkler)}] Bağlanılıyor...")
            
            try:
                driver.get(url)
                time.sleep(4) # PDF ve Blob yüklenmesi için beklemek şart

                # MÜDAHALE NOKTASI (404 Kontrolü)
                if "404" in driver.title or "Server Error" in driver.title:
                    print("      ⚠️  404 Tespit Edildi! 15 sn içinde sayfayı açın...")
                    for k in range(15, 0, -1):
                        print(f"      ⏳  {k}...", end="\r")
                        time.sleep(1)
                
                actual_url = driver.current_url
                print(f"      🌍 AÇILAN SAYFA: {actual_url}")
                
                baslik = driver.title
                try: baslik = driver.find_element(By.TAG_NAME, "h1").text.strip()
                except: pass

                icerik_metni = ""
                pdf_linki = ""
                pdf_bulma_notu = "PDF Bulunamadı"
                pdf_content = None # PDF verisi (bytes)
                
                # --- STRATEJİ 1: Network Sniffing (Blob Dahil) ---
                print("      🕵️  Ağ trafiği taranıyor...")
                try:
                    script = """
                    return window.performance.getEntries()
                        .map(x => x.name)
                        .filter(x => x.toLowerCase().includes('.pdf') || x.toLowerCase().includes('blob:'));
                    """
                    network_files = driver.execute_script(script)
                    if network_files:
                        for f in network_files:
                            if "pdf.worker" in f: continue
                            
                            # YENİ: Blob Linki Yakala
                            if f.startswith("blob:"): 
                                print(f"      🎯 BLOB BULUNDU: {f}")
                                pdf_linki = f
                                pdf_bulma_notu = "Blob (JavaScript)"
                                # Blob'u indir
                                pdf_content = download_blob(driver, f)
                                break 
                            
                            # Normal PDF Linki
                            elif ".pdf" in f:
                                pdf_linki = f
                                pdf_bulma_notu = "Network Sniffing"
                                print(f"      🎯 PDF YAKALANDI: {pdf_linki}")
                                break
                except: pass

                # --- STRATEJİ 2: Viewer Parametreleri (Yedek) ---
                if not pdf_linki:
                    try:
                        current_url_check = driver.current_url
                        if "viewer.html" in current_url_check and "file=" in current_url_check:
                             parts = current_url_check.split("file=")
                             if len(parts) > 1:
                                extracted = unquote(parts[1].split("&")[0])
                                if extracted.startswith("/"): extracted = "https://www.turmob.org.tr" + extracted
                                pdf_linki = extracted
                                pdf_bulma_notu = "URL Parametresi"
                                print(f"      🎯 URL'den Bulundu: {pdf_linki}")
                    except: pass
                
                # --- PDF İŞLEME VE OKUMA ---
                if pdf_linki:
                    try:
                        # Eğer Blob değilse ve henüz indirilmediyse standart indir
                        if not pdf_content and not pdf_linki.startswith("blob:"):
                            resp = requests.get(pdf_linki, headers=HEADERS, verify=False, timeout=30)
                            if resp.status_code == 200:
                                pdf_content = resp.content

                        # PDF Verisi Hazırsa Oku
                        if pdf_content:
                            with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
                                total_pages = len(pdf.pages)
                                print(f"      📊 {total_pages} Sayfa işleniyor...")
                                
                                for page_idx, page in enumerate(pdf.pages):
                                    tablo_verisi = tabloyu_markdown_yap(page)
                                    yazi_verisi = page.extract_text(layout=True) or ""
                                    ocr_verisi = ""
                                    if len(yazi_verisi) < 50:
                                        ocr_verisi = ocr_ile_oku(pdf_content, page_idx)
                                        if ocr_verisi:
                                            yazi_verisi += f"\n[OCR SONUCU]:\n{ocr_verisi}"
                                    icerik_metni += f"\n--- SAYFA {page_idx+1} ---\n{yazi_verisi}\n\n{tablo_verisi}\n"
                            print(f"      ✅ OKUNDU! ({len(icerik_metni)} karakter)")
                        else:
                            print("      ⛔ PDF İçeriği Boş veya İndirilemedi.")

                    except Exception as e:
                        print(f"      ⚠️ İndirme/İşleme Hatası: {e}")
                else:
                    print("      ❌ PDF BULUNAMADI (Blob veya Link yok).")

                if len(icerik_metni) < 50:
                    try: icerik_metni = "ÖZET (HTML):\n" + driver.find_element(By.TAG_NAME, "body").text
                    except: pass

                final_page_url = driver.current_url
                tum_veriler.append({
                    "baslik": baslik,
                    "icerik": icerik_metni,
                    "kaynak": "TÜRMOB Sirküleri",
                    "url": final_page_url,
                    "pdf_url": pdf_linki if pdf_linki else "BULUNAMADI",
                    "debug_notu": pdf_bulma_notu
                })
                print(f"      💾 Başarıyla Eklendi.")

            except Exception as e:
                print(f"      ❌ İşlem Hatası: {e}")

        # KAYDETME
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(tum_veriler, f, ensure_ascii=False, indent=4)
            
        return True, "Tamamlandı"

    except Exception as e:
        print(f"❌ Kritik Hata: {e}")
        return False, str(e)
        
    finally:
        driver.quit()

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings()
    verileri_guncelle()