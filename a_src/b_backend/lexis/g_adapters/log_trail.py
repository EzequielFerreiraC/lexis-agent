"""Trilha de auditoria em JSON por linha no stdout, e o log estruturado do lote em stderr. Na AWS Lambda/ECS, o stdout vai para o CloudWatch Logs;
para retenção imutável, assine o log group com Kinesis Data Firehose -> S3 com Object Lock (ver e_docs)."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, TextIO


class TrilhaLogsJson:
    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdout

    def registrar(self, evento: dict[str, Any]) -> None:
        self.stream.write(json.dumps(evento, ensure_ascii=False) + "\n")
        self.stream.flush()


def configurar_log(stream: TextIO | None = None) -> None:
    """Liga o log estruturado do lote (`lexis.lote`: só ids, hashes, códigos e contagens) a `stderr`, uma linha JSON
    por evento. Chamado pelas entradas (CLI, Lambda); idempotente."""
    logger = logging.getLogger("lexis")
    if any(getattr(h, "_lexis", False) for h in logger.handlers):
        return
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._lexis = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
