"""Encadeamento de hashes da trilha de auditoria: cada evento carrega o hash do anterior.

Alterar, remover ou reordenar uma linha quebra a cadeia a partir dela. Isso torna a adulteração DETECTÁVEL (não a
impede: quem reescreve o arquivo inteiro pode recalcular a cadeia). Impedir é papel do armazenamento imutável
(na AWS, S3 com Object Lock); ver e_docs/f_governance. Funções puras: sem I/O.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

GENESE = "0" * 64
CAMPOS_DO_SELO = ("hash_anterior", "hash")


def _canonico(evento: dict[str, Any]) -> bytes:
    return json.dumps(evento, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def calcular_hash(evento: dict[str, Any], hash_anterior: str) -> str:
    """sha256 do evento (sem o próprio selo) junto com o hash do anterior, em forma canônica."""
    corpo = {k: v for k, v in evento.items() if k not in CAMPOS_DO_SELO}
    return hashlib.sha256(_canonico({**corpo, "hash_anterior": hash_anterior})).hexdigest()


def selar(evento: dict[str, Any], hash_anterior: str) -> dict[str, Any]:
    """O evento com `hash_anterior` e `hash` no fim (a ordem dos demais campos é preservada)."""
    corpo = {k: v for k, v in evento.items() if k not in CAMPOS_DO_SELO}
    return {**corpo, "hash_anterior": hash_anterior, "hash": calcular_hash(corpo, hash_anterior)}


def sem_selo(evento: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in evento.items() if k not in CAMPOS_DO_SELO}


def verificar_cadeia(linhas: list[str]) -> list[str]:
    """Problemas encontrados na cadeia (lista vazia = íntegra). Aponta a PRIMEIRA linha de cada quebra."""
    problemas: list[str] = []
    anterior = GENESE
    for numero, linha in enumerate(linhas, start=1):
        if not linha.strip():
            continue
        try:
            evento = json.loads(linha)
        except json.JSONDecodeError:
            problemas.append(f"linha {numero}: não é JSON válido")
            anterior = ""  # sem como continuar a cadeia: as próximas também acusam
            continue
        if not isinstance(evento, dict) or "hash" not in evento:
            problemas.append(f"linha {numero}: sem selo (hash ausente)")
            anterior = ""
            continue
        if evento.get("hash_anterior") != anterior:
            problemas.append(f"linha {numero}: hash_anterior não confere com a linha anterior (remoção ou reordenação)")
        if evento["hash"] != calcular_hash(evento, str(evento.get("hash_anterior"))):
            problemas.append(f"linha {numero}: conteúdo alterado (hash não confere)")
        anterior = str(evento["hash"])
    return problemas
