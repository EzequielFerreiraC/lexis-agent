"""Adaptador do ambiente: lê as variáveis de ambiente e monta a `Config` (dado puro) que o núcleo recebe.

O núcleo nunca lê `os.environ`; as entradas (CLI, console, Lambda) chamam `config_do_ambiente()` e injetam o resultado.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from lexis.c_extraction.config import Config


def config_do_ambiente(env: Mapping[str, str] | None = None) -> Config:
    e = os.environ if env is None else env
    padrao = Config()
    ent, sai = e.get("LEXIS_PRECO_ENTRADA_USD_MTOK"), e.get("LEXIS_PRECO_SAIDA_USD_MTOK")
    return Config(
        modelo=e.get("LEXIS_MODEL", padrao.modelo),
        timeout_s=float(e.get("LEXIS_TIMEOUT_S", padrao.timeout_s)),
        max_retries=int(e.get("LEXIS_MAX_RETRIES", padrao.max_retries)),
        orcamento_tokens=int(e.get("LEXIS_TOKEN_BUDGET", padrao.orcamento_tokens)),
        api_key=e.get("ANTHROPIC_API_KEY") or None,
        esforco=e.get("LEXIS_EFFORT", padrao.esforco),
        fallbacks=e.get("LEXIS_FALLBACKS", padrao.fallbacks),
        max_tokens=int(e.get("LEXIS_MAX_TOKENS", padrao.max_tokens)),
        workspace_id=e.get("ANTHROPIC_WORKSPACE_ID") or None,
        # só vale com os dois preços definidos (como antes); ilegível vira custo desconhecido em `costs.py`
        preco_override=(ent, sai) if ent and sai else None,
    )
