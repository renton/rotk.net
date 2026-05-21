FROM python:3.12-slim
WORKDIR /rotk.net

ENV FLASK_APP=rotk.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV PYTHONUNBUFFERED=1

# curl is for the docker healthcheck. ca-certificates is for outbound HTTPS
# from the scraper / SMTP client. Everything else (TLS termination, system
# tools) is handled by Caddy from stateful_boilerplate or simply isn't used.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8081

ENTRYPOINT ["./boot.sh"]
