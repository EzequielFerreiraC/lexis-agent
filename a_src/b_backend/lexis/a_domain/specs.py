"""Regras e matriz de aplicabilidade como dado versionado (rules.json)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ARQUIVO = Path(__file__).with_name("rules.json")


@dataclass(frozen=True)
class Specs:
    versao: str
    sha: str
    campos: tuple[str, ...]
    rotulos: dict[str, str]
    tipos: dict[str, dict[str, Any]]
    regras: dict[str, dict[str, str]]
    politica: dict[str, Any]

    def aplicabilidade(self, tipo: str, campo: str) -> str:
        return str(self.tipos[tipo]["aplicabilidade"].get(campo, "opcional"))

    def criticos(self, tipo: str) -> list[str]:
        return list(self.tipos[tipo]["criticos"])

    def severidade(self, regra_id: str) -> str:
        return self.regras[regra_id]["severidade"]

    def descricao(self, regra_id: str) -> str:
        return self.regras[regra_id]["descricao"]


def carregar(caminho: Path = _ARQUIVO) -> Specs:
    bruto = caminho.read_bytes()
    dados = json.loads(bruto)
    # campos de identidade valem para todo tipo de evento: declarados uma vez e aplicados a cada tipo
    tipos = {
        nome: {**t, "aplicabilidade": {**dados["identidade"], **t["aplicabilidade"]}}
        for nome, t in dados["tipos_evento"].items()
    }
    return Specs(
        versao=dados["versao"],
        sha=hashlib.sha256(bruto).hexdigest(),
        campos=tuple(dados["campos"]),
        rotulos=dados["rotulos"],
        tipos=tipos,
        regras=dados["regras"],
        politica=dados["politica"],
    )


SPECS = carregar()
