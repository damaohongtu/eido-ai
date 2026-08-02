FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY extension_updater ./extension_updater

RUN useradd --create-home --uid 10001 updater
USER updater

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=2)"

CMD ["uvicorn", "extension_updater.main:app", "--host", "0.0.0.0", "--port", "8090"]

