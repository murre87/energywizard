# Evaluation only: builds from the repository root. Never used for publishing.
FROM python:3.11.18-slim-trixie@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535 AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_ROOT_USER_ACTION=ignore
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends build-essential gfortran pkg-config libblas-dev liblapack-dev \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir pip==26.3 setuptools==84.2.1 wheel==0.46.3
# Pin the upstream sdist and its PyPI SHA256; no native-CPU compiler tuning.
RUN python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels \
    'https://files.pythonhosted.org/packages/d0/ad/fed0499ce6a338d2a03ebae59cd15093910c8875328855781952abf6c2fe/numpy-2.4.6.tar.gz#sha256=f3a3570c4a2a16746ac2c31a7c7c7b0c186b95ce902e33db6f28094ed7387dda' \
    -Csetup-args=-Dcpu-baseline=none -Csetup-args=-Dblas=blas \
    -Csetup-args=-Dlapack=lapack -Csetup-args=-Dallow-noblas=false -Ccompile-args=-j2

FROM python:3.11.18-slim-trixie@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535 AS openblas-builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_ROOT_USER_ACTION=ignore
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends build-essential gfortran pkg-config libopenblas-pthread-dev \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir pip==26.3 setuptools==84.2.1 wheel==0.46.3
RUN python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels \
    'https://files.pythonhosted.org/packages/d0/ad/fed0499ce6a338d2a03ebae59cd15093910c8875328855781952abf6c2fe/numpy-2.4.6.tar.gz#sha256=f3a3570c4a2a16746ac2c31a7c7c7b0c186b95ce902e33db6f28094ed7387dda' \
    -Csetup-args=-Dcpu-baseline=none -Csetup-args=-Dblas=openblas \
    -Csetup-args=-Dlapack=openblas -Csetup-args=-Dallow-noblas=false -Ccompile-args=-j2

FROM python:3.11.18-slim-trixie@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535 AS upstream
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_ROOT_USER_ACTION=ignore OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends libblas3 liblapack3 qemu-user \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir pip==26.3 setuptools==84.2.1 wheel==0.46.3
COPY smartbox/requirements.txt /tmp/requirements.txt
# The cap remains intact in production; replace it only inside this experiment.
RUN sed '/^numpy[<=>]/d' /tmp/requirements.txt > /tmp/candidate.txt \
    && python -m pip install --no-cache-dir -r /tmp/candidate.txt numpy==2.4.6 \
    && python -m pip check
COPY tests/numpy_compat/smoke.py /smoke.py
COPY tests/numpy_compat/benchmark.py /benchmark.py
CMD ["qemu-x86_64", "-cpu", "qemu64", "/usr/local/bin/python", "/smoke.py"]

FROM upstream AS capped
RUN python -m pip install --no-cache-dir --no-deps --force-reinstall numpy==2.3.5 \
    && python -m pip check

FROM upstream AS candidate
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-deps --force-reinstall /wheels/*.whl \
    && rm -rf /wheels && python -m pip check

FROM upstream AS candidate-openblas
RUN apt-get update && apt-get install -y --no-install-recommends libopenblas0-pthread \
    && rm -rf /var/lib/apt/lists/*
COPY --from=openblas-builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-deps --force-reinstall /wheels/*.whl \
    && rm -rf /wheels && python -m pip check

FROM candidate AS regression
RUN python -m pip install --no-cache-dir pytest
