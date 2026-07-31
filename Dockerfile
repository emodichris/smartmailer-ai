FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system smartmailer && adduser --system --ingroup smartmailer smartmailer

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=smartmailer:smartmailer . .
RUN mkdir -p /app/database && chown smartmailer:smartmailer /app/database

USER smartmailer

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
