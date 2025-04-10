FROM python:3.12
WORKDIR /rotk.net

ENV FLASK_APP rotk.py
ENV FLASK_RUN_HOST 0.0.0.0

RUN sed -i -E 's/MinProtocol[=\ ]+.*/MinProtocol = TLSv1.0/g' /etc/ssl/openssl.cnf

RUN apt-get update && apt-get install -y \
  cron \
  gcc \
  musl-dev \
  openssl \
  ca-certificates \
  apt-transport-https \
  curl \
  gnupg-agent \
  software-properties-common \
  vim \
  && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install -r requirements.txt

EXPOSE 8081

ENTRYPOINT ["./boot.sh"]
