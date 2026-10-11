FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update
RUN apt-get install -y tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng
RUN rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install –upgrade pip
RUN pip install -r requirements.txt

COPY . .

RUN useradd –create-home appuser
USER appuser

CMD [“python”, “-m”, “bot.main”]