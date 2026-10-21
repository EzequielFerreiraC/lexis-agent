"""Adaptadores locais da trilha de auditoria: JSONL em arquivo (execução local) e lista (testes)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from lexis.a_domain.hash_chain import GENESE, selar

_TRAVA = threading.Lock()  # o lote e a revisão humana podem escrever no mesmo arquivo; o selo exige ordem


class TrilhaArquivo:
    """Append-only com encadeamento de hashes (`a_domain/hash_chain.py`): cada linha carrega o hash da anterior,
    lido do próprio arquivo, então a cadeia continua mesmo entre instâncias. Detecta adulteração; não a impede."""

    def __init__(self, arquivo: Path) -> None:
        self.arquivo = arquivo

    def _ultimo_hash(self) -> str:
        if not self.arquivo.is_file():
            return GENESE
        linhas = [x for x in self.arquivo.read_text(encoding="utf-8").splitlines() if x.strip()]
        if not linhas:
            return GENESE
        try:
            return str(json.loads(linhas[-1]).get("hash") or GENESE)
        except (json.JSONDecodeError, AttributeError):
            return GENESE  # linha anterior corrompida: a verificação vai acusar a quebra

    def registrar(self, evento: dict[str, Any]) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        with _TRAVA:
            selado = selar(evento, self._ultimo_hash())
            with self.arquivo.open("a", encoding="utf-8") as f:
                f.write(json.dumps(selado, ensure_ascii=False) + "\n")


class TrilhaMemoria:
    def __init__(self) -> None:
        self.eventos: list[dict[str, Any]] = []

    def registrar(self, evento: dict[str, Any]) -> None:
        self.eventos.append(evento)
