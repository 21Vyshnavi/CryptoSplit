FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/cryptosplit
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir -p /var/lib/cryptosplit/fragments && chown -R 10001:10001 /var/lib/cryptosplit
EXPOSE 8000
ENTRYPOINT ["/srv/cryptosplit/app/entrypoint.sh"]
