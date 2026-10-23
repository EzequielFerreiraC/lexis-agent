#!/usr/bin/env bash
# Para tudo o que o docker compose do Lexis mantém rodando (console e qualquer execução da CLI), sem remover nada:
# os containers continuam existindo, parados. a_start.sh os inicia de novo; c_destroy.sh os remove.
#
#   d_scripts/b_stop.sh [--tempo S]
#
#   --tempo S   segundos de espera pelo encerramento limpo (SIGTERM) antes do SIGKILL (padrão 10)
set -euo pipefail
# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

TEMPO=10
while (( $# )); do
  case $1 in
    --tempo) [[ $# -ge 2 ]] || die "--tempo exige um valor"; TEMPO=$2; shift 2 ;;
    -h|--help) ajuda "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "opção desconhecida: $1 (use --help)" ;;
  esac
done
[[ $TEMPO =~ ^[0-9]+$ ]] || die "--tempo deve ser um número de segundos"

exigir_docker

if [[ -z $(ids_containers) ]]; then
  info "Nenhum container do Lexis existe (nada a parar)."
  exit 0
fi
if [[ -z $(ids_containers --running) ]]; then
  info "Os containers do Lexis já estão parados."
  exit 0
fi

dc_todos stop --timeout "$TEMPO"

if [[ -n $(ids_containers --running) ]]; then
  die "algum container do Lexis continua rodando. Veja: docker compose ps"
fi
ok "Lexis parado. Os containers continuam criados: a_start.sh os inicia de novo; c_destroy.sh os remove."
