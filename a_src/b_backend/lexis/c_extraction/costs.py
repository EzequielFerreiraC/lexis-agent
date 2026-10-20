"""Estimativa de custo por chamada ao modelo. É uma ESTIMATIVA: preços mudam e variam por contrato/plataforma.

Tabela abaixo: preços públicos de lista da Anthropic (USD por milhão de tokens), consultados em 2026-10-17 em
https://platform.claude.com/docs/en/models/overview. Quando o contrato for outro, o preço chega como `override`
(`Config.preco_override`, lido de LEXIS_PRECO_ENTRADA_USD_MTOK e LEXIS_PRECO_SAIDA_USD_MTOK por `g_adapters/ambiente.py`).
Modelo fora da tabela => custo None (nunca inventado).
"""

from __future__ import annotations

PRECOS_USD_POR_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),  # faixa de prompts até 100 mil tokens (acima: 0,50 / 2,50); avisos cabem folgado
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
}
FONTE_PRECOS = "preços públicos de lista (Anthropic), consulta em 2026-10-17; estimativa, sem descontos de cache/lote"


def preco_do_modelo(modelo: str, override: tuple[str, str] | None = None) -> tuple[float, float] | None:
    if override is not None:
        ent, sai = override
        try:
            return float(ent), float(sai)
        except ValueError:
            return None  # override ilegível (ex.: "2,0"): custo desconhecido, nunca derruba o processamento
    return PRECOS_USD_POR_MTOK.get(modelo)


def estimar_custo_usd(
    modelo: str, tokens_entrada: int, tokens_saida: int, override: tuple[str, str] | None = None,
) -> float | None:
    preco = preco_do_modelo(modelo, override)
    if preco is None:
        return None
    return round((tokens_entrada * preco[0] + tokens_saida * preco[1]) / 1_000_000, 6)
