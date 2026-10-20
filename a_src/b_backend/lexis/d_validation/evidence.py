"""Evidência verificável: o trecho citado existe no texto-fonte? Há identificadores omitidos? Há injeção?"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from lexis.a_domain.normalization import (
    canonico,
    todas_as_datas,
    todos_os_decimais,
)

_ISIN = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b")
_TICKER = re.compile(r"\b[A-Z]{4}\d{1,2}\b")
_CNPJ = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")

_INJECAO = {
    "ignorar_instrucoes": re.compile(r"\bignor\w*\b.{0,30}\b(instru\w*|regras?|prompt|orienta\w*|comandos?)\b"),
    "ignore_previous": re.compile(r"\bignore\b.{0,25}\b(previous|prior|above|all|any)\b.{0,25}\b(instructions?|rules?)\b"),
    "desconsidere": re.compile(r"\bdesconsider\w*\b.{0,30}\b(instru\w*|regras?|acima|anterior\w*)\b"),
    "papel_de_modelo": re.compile(r"\b(system prompt|voce (agora )?e (um|uma)|you are (now )?an?)\b"),
    "forcar_aprovacao": re.compile(r"\b(aprov\w+|classifi\w+|marque|defina|set)\b.{0,50}\b(automatic\w+|auto_?aprovad\w*|confianca (alta|maxima)|confidence (high|100))"),
    "evitar_revisao": re.compile(r"\bnao (envie|encaminhe|mande|enviar)\b.{0,40}\brevis\w*"),
    "marcador_de_papel": re.compile(r"(^|\n)\s*(assistant|assistente|system|sistema)\s*:"),
    "tag_de_delimitador": re.compile(r"</?\s*(doc\w*|documento|system|instru\w*)\b"),
    "chamada_de_ferramenta": re.compile(r"\b(tool_use|function_call|registrar_extracao)\b"),
}


@dataclass
class Identificadores:
    isins: set[str]
    tickers: set[str]
    cnpjs: set[str]


def _corta_numero(texto: str, inicio: int, fim: int) -> bool:
    """O trecho texto[inicio:fim] começa ou termina no meio de um número? ("R$ 0,427" dentro de "R$ 0,4275")."""
    def continua(i: int, passo: int) -> bool:
        if not 0 <= i < len(texto):
            return False
        if texto[i].isdigit():
            return True
        # separador de milhar/decimal seguido (ou precedido) de dígito também continua o número
        j = i + passo
        return texto[i] in ".," and 0 <= j < len(texto) and texto[j].isdigit()

    return (texto[inicio].isdigit() and continua(inicio - 1, -1)) or (texto[fim - 1].isdigit() and continua(fim, 1))


def verificar_citacao(
    trecho: str, paginas: list[tuple[int, str]], pagina_sugerida: int | None
) -> tuple[bool, int | None]:
    """O trecho (comparado em forma canônica) existe numa página, sem cortar um número ao meio? Prefere a página
    informada. Sem a checagem de fronteira, uma citação truncada ("0,427" de "0,4275") passaria como literal."""
    alvo = canonico(trecho)
    if not alvo:
        return False, None
    ordem = sorted(paginas, key=lambda p: 0 if p[0] == pagina_sugerida else 1)
    for numero, texto in ordem:
        fonte = canonico(texto)
        i = fonte.find(alvo)
        while i >= 0:
            if not _corta_numero(fonte, i, i + len(alvo)):
                return True, numero
            i = fonte.find(alvo, i + 1)
    return False, None


def varrer_identificadores(texto: str) -> Identificadores:
    return Identificadores(
        isins=set(_ISIN.findall(texto)),
        tickers={t for t in _TICKER.findall(texto)},
        cnpjs=set(_CNPJ.findall(texto)),
    )


def sinais_de_injecao(texto: str) -> list[str]:
    """Heurística de ALERTA (nunca de defesa): a defesa real é o schema estrito + validação no código."""
    c = canonico(texto)
    return sorted(nome for nome, rx in _INJECAO.items() if rx.search(c))


def corrobora(campo: str, valor: Any, texto_ocr: str) -> bool | None:
    """O valor normalizado aparece no texto do OCR? None quando o campo não é verificável assim."""
    if campo.startswith("data_"):
        return valor in todas_as_datas(texto_ocr)
    if campo in {"valor_bruto", "valor_liquido", "custo_atribuido"}:
        return Decimal(valor) in todos_os_decimais(texto_ocr)
    if campo == "aliquota_irrf":
        return (valor * 100) in todos_os_decimais(texto_ocr)
    if campo in {"isin", "ticker"}:
        compacto = re.sub(r"[^A-Za-z0-9]", "", texto_ocr).upper()
        return str(valor) in compacto
    if campo == "cnpj":
        return re.sub(r"\D", "", str(valor)) in re.sub(r"\D", "", texto_ocr)
    if campo == "emissor":
        return canonico(str(valor)) in canonico(texto_ocr)
    return None
