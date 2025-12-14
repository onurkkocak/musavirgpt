# Python 3.11 Sürümü (Daha güncel ve 'importlib' hatalarını çözer)
FROM python:3.11

# Sistemi güncelle, gerekli araçları ve Google Chrome'u .deb paketiyle kur
# Bu yöntem repo eklemekten daha kararlıdır ve 'exit code 127' hatasını çözer.
RUN apt-get update && apt-get install -y wget gnupg2 unzip curl \
    && wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Çalışma klasörünü ayarla
WORKDIR /app

# Kütüphane listesini kopyala ve yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Tüm proje dosyalarını kopyala
COPY . .

# Uygulamayı başlat
CMD ["python", "fastapi_backend.py"]
