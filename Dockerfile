FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    chromium-driver \
    chromium \
    unzip \
    curl \
    && apt-get clean

ENV CHROME_BIN=/usr/bin/chromium
ENV PATH="${CHROME_BIN}:${PATH}"

WORKDIR /app
COPY . /app

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

CMD ["gunicorn", "-b", "0.0.0.0:8000", "app:app"]
