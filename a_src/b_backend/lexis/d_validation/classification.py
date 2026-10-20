"""Classificação determinística por sinais ponderados por zona (título, campo de tipo, corpo).

É a segunda opinião sobre o tipo de evento: se divergir do modelo, o registro vai para revisão.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lexis.a_domain.models import TipoEvento
from lexis.a_domain.normalization import canonico

# (nome do sinal, regex sobre texto canônico, peso base)
_SINAIS: dict[TipoEvento, list[tuple[str, re.Pattern[str], int]]] = {
    TipoEvento.JCP: [
        ("juros_sobre_capital_proprio", re.compile(r"juros sobre (o )?capital proprio"), 3),
        ("sigla_jcp", re.compile(r"\bjcp\b"), 3),
        ("remuneracao_capital_proprio", re.compile(r"remuneracao (do|sobre o) capital proprio"), 3),
        ("tjlp", re.compile(r"\btjlp\b|taxa de juros de longo prazo"), 2),
        ("art9_lei_9249", re.compile(r"art\.? ?9\S* da lei (n\S* )?9\.?249"), 2),
        ("capital_proprio", re.compile(r"capital proprio"), 1),
    ],
    TipoEvento.DIVIDENDO: [
        ("dividendo_intercalar", re.compile(r"dividendos? (intercalares?|intermediari\w+|complementares?)"), 3),
        ("dividendo", re.compile(r"\bdividendos?\b"), 2),
    ],
    TipoEvento.GRUPAMENTO: [
        ("grupamento", re.compile(r"\bgrupamento\b"), 3),
        ("inplit", re.compile(r"\binplit\b|reverse split"), 3),
    ],
    TipoEvento.DESDOBRAMENTO: [
        ("desdobramento", re.compile(r"\bdesdobramento\b"), 3),
        ("split", re.compile(r"\bsplit\b"), 2),
    ],
    TipoEvento.BONIFICACAO: [
        ("bonificacao", re.compile(r"\bbonifica\w+"), 3),
    ],
}
_MULT = {"campo": 3, "titulo": 2, "corpo": 1}
# "imputado ao dividendo mínimo obrigatório" descreve o destino contábil do JCP, não um dividendo.
_CONTEXTO_JCP = re.compile(
    r"(imputad\w+\s+(aos?\s+)?)?dividendos?\s+(minimo\s+)?(obrigatori\w+|minimo)"
    r"|(aos?\s+)?dividendos?\s+obrigatori\w+"
)


@dataclass
class Classificacao:
    tipo: TipoEvento
    pontuacao: dict[str, float]
    por_zona: dict[str, str | None]
    sinais: list[str] = field(default_factory=list)
    conflito_titulo_corpo: bool = False


def _pontuar(texto: str, zona: str) -> tuple[dict[TipoEvento, float], list[str]]:
    pont: dict[TipoEvento, float] = {}
    achados: list[str] = []
    if not texto:
        return pont, achados
    if zona == "corpo":
        texto = _CONTEXTO_JCP.sub(" ", texto)
    for tipo, sinais in _SINAIS.items():
        for nome, rx, peso in sinais:
            if rx.search(texto):
                pont[tipo] = pont.get(tipo, 0) + peso * _MULT[zona]
                achados.append(f"{zona}:{nome}")
    return pont, achados


def _melhor(p: dict[TipoEvento, float]) -> TipoEvento | None:
    if not p:
        return None
    topo = max(p.values())
    lideres = [t for t, v in p.items() if v == topo]
    return lideres[0] if len(lideres) == 1 else None


def classificar(titulo: str | None, campo_tipo: str | None, texto_completo: str) -> Classificacao:
    t = canonico(titulo or "")
    c = canonico(campo_tipo or "")
    corpo = canonico(texto_completo)
    for trecho in (t, c):
        if len(trecho) >= 15:  # trechos curtos ("dividendo") corromperiam o corpo ao serem removidos
            corpo = corpo.replace(trecho, " ")

    total: dict[TipoEvento, float] = {}
    sinais: list[str] = []
    zona_tipo: dict[str, str | None] = {}
    for zona, texto in (("titulo", t), ("campo", c), ("corpo", corpo)):
        p, achados = _pontuar(texto, zona)
        zona_tipo[zona] = (m.value if (m := _melhor(p)) else None)
        sinais += achados
        for tipo, v in p.items():
            total[tipo] = total.get(tipo, 0) + v

    final = _melhor(total) or TipoEvento.OUTRO
    base = zona_tipo["campo"] or zona_tipo["corpo"]
    conflito = bool(zona_tipo["titulo"] and base and zona_tipo["titulo"] != base)
    return Classificacao(
        tipo=final,
        pontuacao={k.value: v for k, v in sorted(total.items(), key=lambda kv: -kv[1])},
        por_zona=zona_tipo,
        sinais=sinais,
        conflito_titulo_corpo=conflito,
    )
