FROM python:3.11-slim

# VIKTIGT, läs innan du ändrar: Home Assistant Supervisor bygger ett tillägg
# med byggkontext satt till tilläggets EGEN mapp (ha-addon/smartbox/), inte
# repots rot - så en vanlig `COPY smartbox/*.py .` här når inte huvudkoden,
# som ligger i en syskonmapp. Löst genom att klona huvudrepot vid byggtillfället
# istället för att duplicera smartbox/-koden in i den här mappen (skulle annars
# behöva hållas manuellt synkad, en garanterad källa till drift mellan de två
# kopiorna). Avsteg, dokumenterat i DOCS.md: kräver internetåtkomst vid bygge
# (precis som pip/apt redan gör), och är pinnad mot en specifik gren/tagg.
ARG ENERGYWIZARD_REF=main
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql postgresql-contrib git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch "${ENERGYWIZARD_REF}" \
        https://github.com/murre87/energywizard /src

WORKDIR /app
RUN cp -r /src/smartbox/. . && rm -rf /src

RUN pip install --no-cache-dir -r requirements.txt

COPY rootfs/run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
