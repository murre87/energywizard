FROM python:3.11-slim

WORKDIR /app

# Kopiera in requirements och installera dem
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiera in alla dina nya .py-filer
COPY *.py .
# drivers/-paketet (EnergyWizard Open: bil/laddare/värmepump/sol/spa-gränssnitt) missades
# tidigare av *.py-mönstret ovan (matchar bara toppnivåfiler) - house_config.py importerar
# från det, så utan den här raden kraschar importen i produktion (upptäckt vid Steg 3).
COPY drivers/ ./drivers/

# Kör hjärnan (unbuffered så loggarna syns direkt)
CMD ["python", "-u", "main.py"]