"""Nome das pastas de saída: `report_yymmdd_hhmm` (ano, mês, dia, hora, minuto; hora local)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

PADRAO_PASTA_RELATORIO = r"report_\d{6}_\d{4}(?:_\d+)?"
PASTA_RELATORIO_RE = re.compile(PADRAO_PASTA_RELATORIO)


def nova_pasta_relatorio(raiz: Path, agora: datetime | None = None) -> Path:
    """Cria `<raiz>/report_yymmdd_hhmm`. Duas execuções no mesmo minuto não se sobrescrevem: a segunda ganha `_2`."""
    base = f"report_{(agora or datetime.now()):%y%m%d_%H%M}"
    raiz.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        pasta = raiz / (base if n == 1 else f"{base}_{n}")
        try:
            pasta.mkdir()
            return pasta
        except FileExistsError:
            n += 1
