FROM python:3.11-slim

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install Chromium and dependencies
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    fonts-liberation \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libgbm-dev \
    wget \
    curl \
    unzip \
    && apt-get clean

# Set Chrome binary path
ENV CHROME_BIN=/usr/bin/chromium

# Set working directory
WORKDIR /app

# Copy project
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port (for gunicorn)
EXPOSE 8000

# Start app
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]
