FROM python:3.10-slim

# Install FFmpeg for audio extraction
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

# Render needs to bind to a port
EXPOSE 10000

CMD ["python", "main.py"]
