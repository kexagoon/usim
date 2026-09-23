FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY src ./src
COPY config ./config
COPY locales ./locales
COPY tests ./tests
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x docker-entrypoint.sh

ENV PYTHONPATH=/app
ENV HOST=0.0.0.0
ENV PORT=8765
ENV USIM_BUILD=freq-compare-2026-09-23
EXPOSE 8765

CMD ["./docker-entrypoint.sh"]
