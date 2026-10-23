#!/usr/bin/env bash
# Utilidades compartilhadas por a_start.sh, b_stop.sh e c_destroy.sh. Não é executado diretamente: só `source`.

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"  # d_scripts/ fica na raiz do repositório
ARQ_COMPOSE="$RAIZ/docker-compose.yml"
SERVICO=console                 # serviço do console web; `cli` é sob demanda (perfil `cli`)

if [[ -t 1 ]]; then
  C_OK=$'\e[32m'; C_AVISO=$'\e[33m'; C_ERRO=$'\e[31m'; C_DIM=$'\e[2m'; C_FIM=$'\e[0m'
else
  C_OK=""; C_AVISO=""; C_ERRO=""; C_DIM=""; C_FIM=""
fi

info()  { printf '%s\n' "$*"; }
ok()    { printf '%s✔%s %s\n' "$C_OK" "$C_FIM" "$*"; }
aviso() { printf '%s!%s %s\n' "$C_AVISO" "$C_FIM" "$*" >&2; }
erro()  { printf '%s✘%s %s\n' "$C_ERRO" "$C_FIM" "$*" >&2; }
die()   { erro "$*"; exit 1; }

# Imprime o bloco de comentário inicial do script (usado em --help).
ajuda() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$1"; }

# docker compose sempre sobre o docker-compose.yml deste repositório (e o .env ao lado dele), de qualquer diretório.
# Só o projeto `lexis` é tocado: os demais containers da máquina não entram.
dc() { docker compose --project-directory "$RAIZ" -f "$ARQ_COMPOSE" "$@"; }
# Idem, incluindo os serviços de perfil (`cli`), para parar/remover também o que o `compose run` deixou.
dc_todos() { dc --profile '*' "$@"; }

exigir_docker() {
  command -v docker >/dev/null || die "docker não encontrado (https://docs.docker.com/engine/install/)."
  docker compose version >/dev/null 2>&1 || die "o plugin 'docker compose' não está instalado."
  [[ -f $ARQ_COMPOSE ]] || die "docker-compose.yml não encontrado em $RAIZ."
  local saida
  saida=$(docker info 2>&1 >/dev/null) \
    || die "não consegui falar com o daemon do Docker (ele está ligado? seu usuário está no grupo 'docker'?): ${saida%%$'\n'*}"
}

# IDs dos containers do projeto (com `-a`, inclui os parados). Uso: ids_containers [--running].
ids_containers() {
  if [[ ${1:-} == --running ]]; then dc_todos ps --status running -q; else dc_todos ps -a -q; fi
}

# Cria o .env a partir do .env.example (se faltar) e gera as senhas do banco que estiverem vazias. As senhas são
# hexadecimais (seguras dentro do LEXIS_DB_URL) e nunca são impressas; o .env fica só para o dono (600).
garantir_env() {
  local env=$RAIZ/.env var
  if [[ ! -f $env ]]; then
    cp "$RAIZ/.env.example" "$env"
    ok ".env criado a partir do .env.example"
  fi
  chmod 600 "$env"
  for var in LEXIS_DB_SENHA LEXIS_DB_SENHA_ROOT; do
    if ! grep -Eq "^${var}=.+" "$env"; then
      sed -i "/^${var}=\s*$/d" "$env"
      printf '%s=%s\n' "$var" "$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')" >> "$env"
      ok "$var gerada no .env"
    fi
  done
}

# Último endereço com token que o console imprimiu (o token muda a cada subida do container).
endereco_console() {
  dc logs --no-log-prefix --no-color "$SERVICO" 2>/dev/null | grep -Eo 'http://[^ ]+#token=[^ ]+' | tail -n 1
}
