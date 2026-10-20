"""Configuração da execução (dado puro). Quem a lê do ambiente é `g_adapters/ambiente.py`; segredos só por variável de ambiente."""

from __future__ import annotations

from dataclasses import dataclass, field

ESFORCOS = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class Config:
    modelo: str = "claude-sonnet-5-5"
    timeout_s: float = 120.0
    max_retries: int = 2
    orcamento_tokens: int = 200_000
    api_key: str | None = field(default=None, repr=False)  # fora do repr: não vaza em log nem em traceback
    # `output_config.effort`: profundidade de raciocínio. Explícito (e gravado) para a execução ser reproduzível.
    esforco: str = "medium"
    # `fallbacks` do servidor: se o classificador de segurança recusar, o próprio provedor tenta outro modelo.
    # O modelo que de fato respondeu é gravado em cada chamada. "off" desliga.
    fallbacks: str = "default"
    max_tokens: int = 16_000
    # Chave de usuário (não vinculada a um workspace) exige o cabeçalho anthropic-workspace-id em toda requisição.
    workspace_id: str | None = None
    # Preço de contrato (USD por milhão de tokens de entrada e de saída), como veio do ambiente; None = tabela pública
    preco_override: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        if self.esforco not in ESFORCOS:
            raise ValueError(f"LEXIS_EFFORT inválido: {self.esforco!r} (use {', '.join(ESFORCOS)})")
        if self.fallbacks not in ("default", "off"):
            raise ValueError(f"LEXIS_FALLBACKS inválido: {self.fallbacks!r} (use default ou off)")
