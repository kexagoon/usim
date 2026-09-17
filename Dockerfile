FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY app ./app
COPY src ./src
COPY config ./config
COPY locales ./locales
COPY tests ./tests

RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir .

ENV HOST=0.0.0.0
ENV PORT=8765
EXPOSE 8765

CMD ["python", "-m", "app.main"]
