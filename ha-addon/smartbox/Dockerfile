FROM python:3.11-slim
# Container builds intentionally install as root; keep pip notices build-only.
ARG PIP_ROOT_USER_ACTION=ignore
ARG PIP_DISABLE_PIP_VERSION_CHECK=1

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

# Commit-id:t gör att byggcachen inte återanvänder en gammal klon (sätts av CI, tomt annars).
ARG ENERGYWIZARD_COMMIT=
# Versionen i telemetrin (commit, kortas till 7 tecken i telemetry.py). Tom när HA bygger själv.
ENV APP_VERSION=${ENERGYWIZARD_COMMIT}
# Repot att klona: standard är projektet självt; CI sätter forkens adress för pull requests från forkar
# (grenen finns bara där, annars misslyckas kloningen).
ARG ENERGYWIZARD_REPO=https://github.com/murre87/energywizard
# Byggcachen får ALDRIG återanvända en gammal klon (2026-11-04, #125: tilläggsanvändare fick gammal kod trots ny
# version, eftersom kloningssteget såg likadant ut varje gång när HA bygger själv). Två skydd:
#  - BUILD_VERSION sätts av Home Assistant (tilläggets version) - ny version = ny klon.
#  - ADD av grenens senaste commit från GitHub: Docker jämför innehållet, så en ändrad main ger alltid en ny klon.
ARG BUILD_VERSION=
ADD https://github.com/murre87/energywizard/commits/main.atom /tmp/energywizard-main.json
# Med ENERGYWIZARD_COMMIT (CI) checkas exakt den commiten ut, så att den färdiga bilden för en version innehåller den
# kod versionen byggdes från även om main hunnit flytta sig under bygget.
RUN echo "EnergyWizard ${ENERGYWIZARD_REPO} ${ENERGYWIZARD_REF} ${ENERGYWIZARD_COMMIT} ${BUILD_VERSION}" && git clone --depth 1 --branch "${ENERGYWIZARD_REF}" \
        "${ENERGYWIZARD_REPO}" /src && rm -f /tmp/energywizard-main.json \
    && if [ -n "${ENERGYWIZARD_COMMIT}" ] && [ "$(git -C /src rev-parse HEAD)" != "${ENERGYWIZARD_COMMIT}" ]; then \
         git -C /src fetch --depth 1 origin "${ENERGYWIZARD_COMMIT}" && git -C /src checkout -q "${ENERGYWIZARD_COMMIT}"; fi

# Samma layout som docker-compose-driften: ewapp och webdashboard gör
# sys.path.insert(0, "/smartbox") och importerar motorns moduler därifrån
# (i compose: ./smartbox monterad på /smartbox), så motorn ligger i /smartbox.
RUN cp -r /src/smartbox /smartbox \
    && (git -C /src rev-parse --short HEAD > /smartbox/VERSION || true) \
    && cp -r /src/ewapp /ewapp \
    && cp -r /src/webdashboard /webdashboard \
    && cp /src/LICENSE /LICENSE && cp /src/LICENSE /smartbox/LICENSE \
    && rm -rf /src

# Motorns beroenden + det gränssnitten installerar i sina egna Dockerfiles
# (ewapp/Dockerfile, webdashboard/Dockerfile) - samma paket, en gemensam miljö.
RUN pip install --no-cache-dir -r /smartbox/requirements.txt \
    && pip install --no-cache-dir fastapi "uvicorn[standard]" requests sqlalchemy \
        "psycopg[binary]" psycopg_pool pandas "numpy<2.4" PyYAML pymodbus pillow

# ewapp/Dockerfile genererar PWA-ikonerna vid bygge - samma steg här.
RUN cd /ewapp && python make_icons.py

WORKDIR /smartbox

COPY rootfs/run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8502 8503
VOLUME /data
CMD ["/run.sh"]
