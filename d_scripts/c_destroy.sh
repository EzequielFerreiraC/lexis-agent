#!/usr/bin/env bash
# Remove os containers do Lexis e a rede do projeto (docker compose down), inclusive órfãos e os da CLI.
# Pede confirmação, a menos que use --sim. Nunca apaga seus dados: f_data/b_output, c_replay/ e .env são pastas/arquivos
# do host (montados no container), não fazem parte do que o compose remove.
#
#   d_scripts/c_destroy.sh [--imagens] [--sim] [--listar]
#
#   --imagens   remove também a imagem lexis:local (o próximo a_start.sh reconstrói; demora mais)
#   --sim       não pergunta (necessário sem terminal interativo)
#   --listar    só mostra o que seria removido; não remove nada
set -euo pipefail
# shellcheck source=_common.sh
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

IMAGENS=0
SIM=0
SO_LISTAR=0
while (( $# )); do
  case $1 in
    --imagens) IMAGENS=1; shift ;;
    --sim|-y) SIM=1; shift ;;
    --listar) SO_LISTAR=1; shift ;;
    -h|--help) ajuda "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "opção desconhecida: $1 (use --help)" ;;
  esac
done

exigir_docker

IMAGEM=$(dc config --images 2>/dev/null | sort -u | head -n 1)
IMAGEM_EXISTE=0
[[ -z $IMAGEM ]] || ! docker image inspect "$IMAGEM" >/dev/null 2>&1 || IMAGEM_EXISTE=1

if [[ -z $(ids_containers) ]]; then
  info "Nenhum container do Lexis para remover."
  if (( IMAGENS && IMAGEM_EXISTE )); then
    info "A imagem $IMAGEM existe e será removida com --imagens."
  else
    exit 0
  fi
else
  info "Containers do Lexis:"
  dc_todos ps -a --format 'table {{.Name}}\t{{.Service}}\t{{.Status}}'
  info ""
  info "Serão removidos: os containers acima e a rede do projeto."
fi
if (( IMAGENS && IMAGEM_EXISTE )); then info "Também será removida a imagem: $IMAGEM"; fi
info "${C_DIM}Seus dados (f_data/b_output, c_replay/, .env e o volume do banco mysql_dados) não são tocados.${C_FIM}"

if (( SO_LISTAR )); then exit 0; fi
if (( ! SIM )); then
  [[ -t 0 ]] || die "sem terminal interativo: use --sim para confirmar (ou --listar para só listar)."
  read -rp "Confirmar a remoção? [s/N] " RESP
  [[ ${RESP,,} == s || ${RESP,,} == sim ]] || { info "Nada removido."; exit 0; }
fi

args=(down --remove-orphans)
(( IMAGENS )) && args+=(--rmi all)
dc_todos "${args[@]}"

if [[ -n $(ids_containers) ]]; then
  die "ainda restam containers do Lexis. Veja: docker compose ps -a"
fi
ok "Containers e rede do Lexis removidos$( (( IMAGENS )) && echo ', junto com a imagem')."
info "${C_DIM}Para subir de novo: d_scripts/a_start.sh${C_FIM}"
