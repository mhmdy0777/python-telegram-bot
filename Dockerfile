FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 
PYTHONUNBUFFERED=1 
PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update 
&& apt-get install -y –no-install-recommends tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng tesseract-ocr-uzb 
&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install –upgrade pip 
&& pip install -r requirements.txt

COPY . .

RUN useradd –create-home appuser

USER appuser

CMD [“python”, “-m”, “bot.main”]