# syntax=docker/dockerfile:1
FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends nut-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8484
CMD ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8484", "--proxy-headers"]
