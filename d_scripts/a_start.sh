#!/usr/bin/env bash
# Sobe o console web do Lexis em container (docker compose up -d) e imprime o endereço com o token.
# Constrói a imagem se preciso e espera o healthcheck. Se já estiver no ar, só mostra o endereço atual.
# Containers parados (b_stop.sh) são iniciados de novo; o token muda a cada subida.
#
#   d_scripts/a_start.sh [--porta N] [--rebuild] [--sem-build] [--verificar]
#
#   --porta N     porta no host (padrão: LEXIS_PORTA do .env ou 8000; publicada só em 127.0.0.1)
#   --rebuild     reconstrói a imagem do zero, sem cache (ex.: dependências ou front mudaram)
#   --sem-build   não reconstrói a imagem: usa a lexis:local que já existe
#   --verificar   só confere Docker, compose e porta; não sobe nada
set -euo pipefail
# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

PORTA=""
REBUILD=0
SEM_BUILD=0
SO_VERIFICAR=0
while (( $# )); do
  case $1 in
    --porta) [[ $# -ge 2 ]] || die "--porta exige um valor"; PORTA=$2; shift 2 ;;
    --rebuild) REBUILD=1; shift ;;
    --sem-build) SEM_BUILD=1; shift ;;
    --verificar) SO_VERIFICAR=1; shift ;;
    -h|--help) ajuda "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "opção desconhecida: $1 (use --help)" ;;
  esac
done
(( ! (REBUILD && SEM_BUILD) )) || die "--rebuild e --sem-build são excludentes."
if [[ -n $PORTA ]]; then
  [[ $PORTA =~ ^[0-9]+$ ]] && (( PORTA >= 1024 && PORTA <= 65535 )) || die "--porta deve estar entre 1024 e 65535"
  export LEXIS_PORTA=$PORTA
fi

exigir_docker
ok "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?') · $(docker compose version --short)"
garantir_env
dc config -q || die "docker-compose.yml inválido (veja a mensagem acima)."
ok "docker-compose.yml válido"
grep -Eq '^ANTHROPIC_API_KEY=.+' "$RAIZ/.env" || aviso "sem ANTHROPIC_API_KEY no .env: só os modos de demonstração (replay) funcionam."

# Porta ocupada por outro processo? Se o console do Lexis já está rodando, a porta é dele mesmo.
rodando=$(dc ps --status running -q "$SERVICO")
if [[ -z $rodando ]]; then
  PORTA_EFETIVA=${LEXIS_PORTA:-}
  if [[ -z $PORTA_EFETIVA && -f $RAIZ/.env ]]; then
    PORTA_EFETIVA=$(sed -n 's/^LEXIS_PORTA=//p' "$RAIZ/.env" | tail -n 1 | tr -d '\r"')
  fi
  PORTA_EFETIVA=${PORTA_EFETIVA:-8000}
  if ss -ltn "sport = :$PORTA_EFETIVA" 2>/dev/null | grep -q LISTEN; then
    die "a porta $PORTA_EFETIVA já está em uso. Use --porta para escolher outra."
  fi
fi

if (( SO_VERIFICAR )); then
  ok "Ambiente pronto (--verificar: nada foi iniciado)."
  exit 0
fi

# ---------------------------------------------------------------- Subida
if (( REBUILD )); then
  info "Reconstruindo a imagem sem cache ..."
  dc build --no-cache "$SERVICO"
fi
args=(up -d --wait --wait-timeout 180)  # a primeira subida do MySQL inicializa o banco
(( SEM_BUILD )) || args+=(--build)
info "docker compose ${args[*]} $SERVICO"
dc "${args[@]}" "$SERVICO" || {
  erro "o console não ficou saudável. Últimas linhas do log:"
  dc logs --no-color --tail 20 "$SERVICO" >&2 || true
  exit 1
}

ENDERECO=$(endereco_console)
if [[ -z $ENDERECO ]]; then
  aviso "console no ar, mas o endereço não apareceu no log. Rode: docker compose logs $SERVICO"
  exit 0
fi
ok "Lexis no ar (container $SERVICO)"
info ""
info "  $ENDERECO"
info ""
info "${C_DIM}O token muda a cada subida. Parar: d_scripts/b_stop.sh · remover: d_scripts/c_destroy.sh${C_FIM}"
info "${C_DIM}Login: crie um usuário com  docker compose run --rm cli usuario criar <login> --nome \"<Nome>\"${C_FIM}"
