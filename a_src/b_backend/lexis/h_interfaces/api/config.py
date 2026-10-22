"""Configuração do servidor local. Todos os caminhos vêm daqui (linha de comando/ambiente), NUNCA do navegador."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lexis.c_extraction.config import Config
from lexis.g_adapters.ambiente import config_do_ambiente


@dataclass(frozen=True)
class ConfigServidor:
    token: str
    raiz_amostras: Path = Path("f_data/a_input")
    golden_csv: Path = Path("f_data/c_golden_records/golden_records.csv")
    dir_replay: Path = Path("c_replay")
    dir_execucoes: Path = Path("f_data/b_output")
    dir_front: Path = Path("a_src/a_frontend/dist")
    max_arquivos: int = 20
    max_por_pagina: int = 100
    # Banco (LEXIS_DB_URL): com ele, cada execução e revisão vira projeção consultável e o console exige login
    db_url: str | None = None
    # LEXIS_DOMINIOS_EMAIL: só e-mails destes domínios criam conta pelo console; vazio = qualquer domínio
    dominios_email: tuple[str, ...] = ()
    cookie_seguro: bool = False  # True atrás de TLS; o console local é http://127.0.0.1
    cfg: Config = field(default_factory=config_do_ambiente)


def dominios_do_ambiente(valor: str) -> tuple[str, ...]:
    """`empresa.com.br, filial.com` -> ("empresa.com.br", "filial.com"); aceita com ou sem `@`."""
    return tuple(d for d in (p.strip().lower().lstrip("@") for p in valor.split(",")) if d)
