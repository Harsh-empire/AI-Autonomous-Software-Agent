FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt || pip install fastapi uvicorn websockets requests openai flask flask-sqlalchemy

COPY . .

EXPOSE 8000
EXPOSE 5000

ENV PYTHONUNBUFFERED=1

CMD ["python", "ide_server.py"]
