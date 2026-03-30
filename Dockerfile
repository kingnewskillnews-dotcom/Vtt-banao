FROM python:3.10-slim

# Install FFmpeg for audio processing
RUN apt-get update && \
    apt-get install -y ffmpeg wget git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render port expose
EXPOSE 10000

CMD ["python", "main.py"]
