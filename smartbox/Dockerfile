FROM python:3.11-slim

WORKDIR /app

# Kopiera in requirements och installera dem
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiera in alla dina nya .py-filer
COPY *.py .

# Kör hjärnan (unbuffered så loggarna syns direkt)
CMD ["python", "-u", "main.py"]