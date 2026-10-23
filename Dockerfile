# syntax=docker/dockerfile:1
# Imagem do Lexis: console web (API + front compilado) e CLI `lexis`. Uso pelo docker-compose.yml.
#
# Mesmas garantias da instalação local: dependências Python só do lockfile com hashes (requirements.txt) e
# `npm ci` no front. O pacote não é instalado (instalar exigiria baixar o setuptools sem hash): roda por PYTHONPATH.
# Com Tesseract (português): o scan ganha um leitor independente do modelo, gravado em c_replay/<sha>/ocr.json.

# ---------------------------------------------------------------- front (build estático)
FROM node:24-bookworm-slim AS front
WORKDIR /front
COPY a_src/a_frontend/package.json a_src/a_frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY a_src/a_frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- execução
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/a_src/b_backend \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    # report_yymmdd_hhmm usa a hora local; sem TZ o container usaria UTC (sobrescreva no .env)
    TZ=America/Sao_Paulo

# Mesmo uid/gid do usuário do host: o que o container grava em f_data/b_output continua sendo do usuário
ARG LEXIS_UID=1000
ARG LEXIS_GID=1000
RUN groupadd --gid "$LEXIS_GID" lexis \
    && useradd --uid "$LEXIS_UID" --gid "$LEXIS_GID" --no-create-home --shell /usr/sbin/nologin lexis

# OCR local: leitor independente do modelo para scans (g_adapters/tesseract_ocr.py)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --require-hashes -r requirements.txt

COPY a_src/b_backend/ a_src/b_backend/
COPY --from=front /front/dist/ a_src/a_frontend/dist/
# Dados de referência, amostras e gravações: a imagem funciona sozinha (o compose também os monta do repo)
COPY f_data/a_input/ f_data/a_input/
COPY f_data/c_golden_records/ f_data/c_golden_records/
COPY c_replay/ c_replay/
RUN mkdir -p f_data/b_output && chown lexis:lexis f_data/b_output

USER lexis
EXPOSE 8000
ENTRYPOINT ["python", "-m", "lexis"]
CMD ["serve", "--container", "--porta", "8000"]
