"""Normalização determinística: texto literal -> valor tipado. O modelo nunca normaliza."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
TICKER_RE = re.compile(r"^[A-Z]{4}\d{1,2}$")
CNPJ_RE = re.compile(r"^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$")

_MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}
_DATA_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_DATA_EXT = re.compile(r"\b(\d{1,2})\s*º?\s+de\s+([a-zç]+)\s+de\s+(\d{4})\b", re.IGNORECASE)
_NUM_BR = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?")
_PCT = re.compile(r"(\d+(?:,\d+)?)\s*%")
_PROP_RAZAO = re.compile(r"\b(\d+)\s*:\s*(\d+)\b")
_ACAO = r"a[cç](?:[aã]o|[oõ]es)"
# aceita o número por extenso entre parênteses, como na redação padrão: "1 (uma) ação nova para cada 20 (vinte)"
_PROP_NOVAS = re.compile(rf"\b(\d+)\s*(?:\([^)]*\))?\s*{_ACAO}\s+nova[s]?\s+para\s+cada\s+(\d+)\b", re.I)
_PROP_PARA = re.compile(rf"\b(\d+)\s*(?:\([^)]*\))?\s*{_ACAO}\s+existentes?\s+para\s+(\d+)\b", re.I)


def sem_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def canonico(s: str) -> str:
    """Forma usada para comparar trechos: NFKC, sem acentos, minúsculas, espaços colapsados."""
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", " ", sem_acentos(s).casefold()).strip()


def nome_emissor_canonico(s: str) -> str:
    base = re.sub(r"[^a-z0-9 ]", " ", canonico(s))
    tokens = [t for t in base.split() if t not in {"s", "a", "sa", "cia", "companhia"}]
    return " ".join(tokens)


@dataclass(frozen=True)
class Proporcao:
    termo_a: int
    termo_b: int
    percentual: Decimal | None
    forma: str  # RAZAO | NOVAS_PARA_CADA | EXISTENTES_PARA


@dataclass
class Normalizado:
    valor: Any
    repr: str
    detalhe: dict[str, str] = field(default_factory=dict)


def _datas(texto: str) -> set[date]:
    achadas: set[date] = set()
    for d, m, a in _DATA_NUM.findall(texto):
        try:
            achadas.add(date(int(a), int(m), int(d)))
        except ValueError:
            return set()
    for d, mes, a in _DATA_EXT.findall(texto):
        n = _MESES.get(sem_acentos(mes.lower()))
        if n is None:
            continue
        try:
            achadas.add(date(int(a), n, int(d)))
        except ValueError:
            return set()
    return achadas


def todas_as_datas(texto: str) -> set[date]:
    return _datas(texto)


def parse_data(texto: str) -> date | None:
    achadas = _datas(texto)
    return next(iter(achadas)) if len(achadas) == 1 else None


def _decimal(token: str) -> Decimal | None:
    try:
        return Decimal(token.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def todos_os_decimais(texto: str) -> set[Decimal]:
    return {d for t in _NUM_BR.findall(texto) if (d := _decimal(t)) is not None}


def parse_decimal(texto: str) -> Decimal | None:
    tokens = _NUM_BR.findall(texto)
    return _decimal(tokens[0]) if len(tokens) == 1 else None


def parse_percentual(texto: str) -> Decimal | None:
    achados = _PCT.findall(texto)
    if len(achados) != 1:
        return None
    d = _decimal(achados[0])
    return None if d is None else d / Decimal(100)


def parse_proporcao(texto: str) -> Proporcao | None:
    pct = _PCT.findall(texto)
    percentual = _decimal(pct[0]) if len(pct) == 1 else None
    for padrao, forma in (
        (_PROP_NOVAS, "NOVAS_PARA_CADA"),
        (_PROP_PARA, "EXISTENTES_PARA"),
        (_PROP_RAZAO, "RAZAO"),
    ):
        m = padrao.search(texto)
        if m:
            return Proporcao(int(m.group(1)), int(m.group(2)), percentual, forma)
    return None


def parse_moeda(texto: str) -> str | None:
    t = texto.upper()
    if "US$" in t or "USD" in t:
        return "USD"
    if "R$" in t or "BRL" in t or "REAIS" in t:
        return "BRL"
    return None


def parse_classe(texto: str) -> str | None:
    t = canonico(texto)
    m = re.search(r"\b(pnb|pna|pn|on|unit|unt)\b", t)
    if m:
        return m.group(1).upper()
    if "ordinaria" in t:
        return "ON"
    if "preferencial" in t:
        return "PN"
    return None


TEXTO_LIVRE = {"emissor", "observacao_tributaria"}


def equivalentes(campo: str, a: Normalizado, b: Normalizado) -> bool:
    """Duas leituras do mesmo campo dizem o mesmo? Texto livre ignora caixa, espaços/quebras e pontuação final
    (as duas leituras do scan citam a mesma frase com ou sem o ponto); os demais comparam o valor normalizado."""
    if campo in TEXTO_LIVRE:
        return canonico(a.repr).rstrip(" .;,") == canonico(b.repr).rstrip(" .;,")
    return a.repr == b.repr


def normalizar(campo: str, texto: str) -> Normalizado | None:
    """Converte o texto literal de `campo`; None quando não interpretável sem ambiguidade."""
    t = texto.strip()
    if campo.startswith("data_"):
        d = parse_data(t)
        return None if d is None else Normalizado(d, d.isoformat())
    if campo in {"valor_bruto", "valor_liquido", "custo_atribuido"}:
        valor = parse_decimal(t)
        if valor is None:
            return None
        return Normalizado(valor, format(valor, "f"), {"moeda_no_trecho": parse_moeda(t) or ""})
    if campo == "aliquota_irrf":
        pct = parse_percentual(t)
        if pct is None:
            return None
        return Normalizado(pct, format(pct, "f"), {"percentual": format(pct * 100, "f") + "%"})
    if campo == "moeda":
        m = parse_moeda(t)
        return None if m is None else Normalizado(m, m)
    if campo == "proporcao":
        pr = parse_proporcao(t)
        if pr is None:
            return None
        det = {"termo_a": str(pr.termo_a), "termo_b": str(pr.termo_b), "forma": pr.forma}
        if pr.percentual is not None:
            det["percentual_declarado"] = format(pr.percentual, "f")
        return Normalizado(pr, f"{pr.termo_a}:{pr.termo_b}", det)
    if campo == "classe_acao":
        c = parse_classe(t)
        return None if c is None else Normalizado(c, c)
    if campo == "isin":
        ident = re.sub(r"[\s-]", "", t).upper()
        return Normalizado(ident, ident)
    if campo == "ticker":
        ident = re.sub(r"\s", "", t).upper()
        return Normalizado(ident, ident)
    if campo == "cnpj":
        return Normalizado(t, t)
    return Normalizado(t, t)  # emissor, observacao_tributaria
