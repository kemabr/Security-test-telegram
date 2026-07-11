FROM openjdk:17-slim

# Sistem paketleri
RUN apt-get update && apt-get install -y \
    wget \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# JMeter indir ve kur
RUN wget -q https://dlcdn.apache.org//jmeter/binaries/apache-jmeter-5.6.3.tgz \
    && tar -xzf apache-jmeter-5.6.3.tgz -C /opt/ \
    && ln -s /opt/apache-jmeter-5.6.3/bin/jmeter /usr/local/bin/jmeter \
    && rm apache-jmeter-5.6.3.tgz

# Python bağımlılıkları
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Uygulama
COPY . .

CMD ["python3", "bot.py"]
