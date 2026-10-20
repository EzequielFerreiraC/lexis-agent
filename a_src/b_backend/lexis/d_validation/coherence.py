"""Regras de coerência. Funções puras: recebem valores já normalizados e devolvem resultados auditáveis."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from lexis.a_domain.market_calendar import ANOS_COBERTOS, coberto, proximo_dia_util
from lexis.a_domain.models import RegraResultado, Severidade, TipoEvento, ValidacaoGolden
from lexis.a_domain.normalization import CNPJ_RE, ISIN_RE, TICKER_RE, Proporcao
from lexis.a_domain.specs import SPECS

Dados = dict[str, Any]  # campo -> valor normalizado (date, Decimal, str, Proporcao)


def _res(
    regra_id: str, ok: bool | None, campos: list[str], detalhe: str,
    esperado: str | None = None, observado: str | None = None,
) -> RegraResultado:
    """ok=None => não aplicável (entradas ausentes)."""
    return RegraResultado(
        id=regra_id,
        severidade=Severidade(SPECS.severidade(regra_id)),
        resultado="NAO_APLICAVEL" if ok is None else "OK" if ok else "FALHA",
        campos=campos, detalhe=detalhe, esperado=esperado, observado=observado,
    )


resultado_de_regra = _res


def checar_formatos(dados: Dados) -> list[RegraResultado]:
    saida = []
    for campo, rx, regra in (
        ("isin", ISIN_RE, "FORMATO_ISIN"), ("ticker", TICKER_RE, "FORMATO_TICKER"),
        ("cnpj", CNPJ_RE, "FORMATO_CNPJ"),
    ):
        if campo in dados:
            ok = bool(rx.match(str(dados[campo])))
            saida.append(_res(regra, ok, [campo], SPECS.descricao(regra), observado=str(dados[campo])))
    return saida


def checar_datas(tipo: TipoEvento, dados: Dados) -> list[RegraResultado]:
    aprov, com, ex = dados.get("data_aprovacao"), dados.get("data_com"), dados.get("data_ex")
    pag, cred = dados.get("data_pagamento"), dados.get("data_credito_ativos")
    r: list[RegraResultado] = []

    def iso(d: date | None) -> str | None:
        return d.isoformat() if d else None

    r.append(_res(
        "DATAS_EX_NAO_POSTERIOR_A_COM", None if not (com and ex) else ex > com, ["data_com", "data_ex"],
        "Data ex deve ser posterior à data com.", "data_ex > data_com",
        f"data_com={iso(com)}, data_ex={iso(ex)}",
    ))
    if SPECS.aplicabilidade(tipo.value, "data_pagamento") != "nao_aplicavel":
        r.append(_res(
            "DATAS_PAGAMENTO_ANTES_DA_COM", None if not (com and pag) else pag >= com,
            ["data_pagamento", "data_com"], "Pagamento não pode anteceder a data com.",
            "data_pagamento >= data_com", f"data_pagamento={iso(pag)}, data_com={iso(com)}",
        ))
        r.append(_res(
            "DATAS_PAGAMENTO_ANTES_DA_EX", None if not (ex and pag) else pag >= ex,
            ["data_pagamento", "data_ex"], "Pagamento não pode anteceder a data ex.",
            "data_pagamento >= data_ex", f"data_pagamento={iso(pag)}, data_ex={iso(ex)}",
        ))
    if SPECS.aplicabilidade(tipo.value, "data_credito_ativos") != "nao_aplicavel":
        r.append(_res(
            "DATAS_CREDITO_ANTES_DA_COM", None if not (com and cred) else cred >= com,
            ["data_credito_ativos", "data_com"], "Crédito das ações não pode anteceder a data com.",
            "data_credito_ativos >= data_com", f"data_credito_ativos={iso(cred)}, data_com={iso(com)}",
        ))
    r.append(_res(
        "DATAS_APROVACAO_APOS_COM", None if not (aprov and com) else aprov <= com,
        ["data_aprovacao", "data_com"], "Aprovação costuma anteceder a data com.",
        "data_aprovacao <= data_com", f"data_aprovacao={iso(aprov)}, data_com={iso(com)}",
    ))
    if com and ex:
        esperado = proximo_dia_util(com)
        com_calendario = coberto(com) and coberto(esperado)
        r.append(_res(
            "DATAS_EX_NAO_E_DIA_UTIL_SEGUINTE", ex == esperado, ["data_com", "data_ex"],
            "Dia útil pelo calendário de feriados da B3 (fins de semana, feriados nacionais, Carnaval, Sexta-feira Santa, "
            "Corpus Christi, 24 e 31/12)." if com_calendario else
            f"Fora dos anos cobertos pelo calendário da B3 ({ANOS_COBERTOS.start}-{ANOS_COBERTOS[-1]}): só considera sábados e domingos.",
            f"data_ex={esperado.isoformat()}", f"data_ex={ex.isoformat()}",
        ))
    fds = [c for c in ("data_com", "data_ex", "data_pagamento") if isinstance(dados.get(c), date) and dados[c].weekday() >= 5]
    r.append(_res("DATA_FIM_DE_SEMANA", not fds, fds, SPECS.descricao("DATA_FIM_DE_SEMANA"),
                  observado=", ".join(f"{c}={dados[c].isoformat()}" for c in fds) or None))
    if aprov:
        r.append(_res("DATA_APROVACAO_FIM_DE_SEMANA", aprov.weekday() < 5, ["data_aprovacao"],
                      SPECS.descricao("DATA_APROVACAO_FIM_DE_SEMANA"), observado=aprov.isoformat()))
        limite = int(SPECS.politica["faixa_plausivel_dias"])
        longe = [
            c for c in ("data_com", "data_ex", "data_pagamento", "data_credito_ativos")
            if isinstance(dados.get(c), date) and abs((dados[c] - aprov).days) > limite
        ]
        r.append(_res("DATAS_FORA_DA_FAIXA", not longe, longe,
                      f"Datas a mais de {limite} dias da aprovação sugerem erro de leitura (ex.: ano).",
                      observado=", ".join(f"{c}={dados[c].isoformat()}" for c in longe) or None))
    return r


def _casas(d: Decimal) -> int:
    exp = d.as_tuple().exponent
    return -exp if isinstance(exp, int) and exp < 0 else 0


def checar_tributacao(tipo: TipoEvento, dados: Dados) -> list[RegraResultado]:
    bruto, liq = dados.get("valor_bruto"), dados.get("valor_liquido")
    aliq = dados.get("aliquota_irrf")
    r: list[RegraResultado] = []
    valores = {c: dados[c] for c in ("valor_bruto", "valor_liquido", "custo_atribuido") if c in dados}
    if valores:
        ruins = [c for c, v in valores.items() if v <= 0]
        r.append(_res("VALOR_NAO_POSITIVO", not ruins, list(valores), SPECS.descricao("VALOR_NAO_POSITIVO"),
                      observado=", ".join(f"{c}={valores[c]}" for c in ruins) or None))
    if liq is not None and aliq is None:
        r.append(_res("TRIB_LIQUIDO_SEM_ALIQUOTA", False, ["valor_liquido", "aliquota_irrf"],
                      SPECS.descricao("TRIB_LIQUIDO_SEM_ALIQUOTA")))
    if bruto is not None and liq is not None and aliq is not None:
        esperado = bruto * (Decimal(1) - aliq)
        tol = Decimal(10) ** -_casas(liq) * Decimal(str(SPECS.politica["tolerancia_liquido_ulp"]))
        ok = abs(liq - esperado) <= tol
        r.append(_res(
            "TRIB_LIQUIDO_DIVERGE", ok, ["valor_bruto", "aliquota_irrf", "valor_liquido"],
            "Líquido esperado = bruto × (1 − alíquota informada no aviso); tolerância de 0,5 unidade da última casa do líquido (arredondamento).",
            esperado=format(esperado, "f"), observado=format(liq, "f"),
        ))
    if tipo is TipoEvento.DIVIDENDO and bruto is not None and liq is not None:
        r.append(_res(
            "TRIB_DIVIDENDO_COM_RETENCAO", not (liq < bruto), ["valor_liquido", "valor_bruto"],
            "Dividendo com líquido menor que o bruto indica retenção por ação, típica de JCP.",
            esperado="líquido = bruto (ou ausente)", observado=f"bruto={bruto}, líquido={liq}",
        ))
    return r


def checar_proporcao(tipo: TipoEvento, dados: Dados) -> list[RegraResultado]:
    p = dados.get("proporcao")
    if not isinstance(p, Proporcao):
        return []
    r = [_res("PROP_INVALIDA", p.termo_a > 0 and p.termo_b > 0 and p.termo_a != p.termo_b, ["proporcao"],
              SPECS.descricao("PROP_INVALIDA"), observado=f"{p.termo_a}:{p.termo_b}")]
    if tipo is TipoEvento.GRUPAMENTO:
        ok = p.forma != "NOVAS_PARA_CADA" and p.termo_a > p.termo_b
        r.append(_res("PROP_SENTIDO_INCOMPATIVEL", ok, ["proporcao"],
                      "Grupamento reduz a quantidade de ações: termo existente > termo resultante.",
                      "antes > depois", f"{p.termo_a}:{p.termo_b} ({p.forma})"))
    elif tipo is TipoEvento.DESDOBRAMENTO:
        ok = p.forma != "NOVAS_PARA_CADA" and p.termo_a < p.termo_b
        r.append(_res("PROP_SENTIDO_INCOMPATIVEL", ok, ["proporcao"],
                      "Desdobramento aumenta a quantidade de ações: antes < depois.",
                      "antes < depois", f"{p.termo_a}:{p.termo_b} ({p.forma})"))
    elif tipo is TipoEvento.BONIFICACAO and p.percentual is not None and p.termo_b > 0:
        razao = Decimal(p.termo_a) / Decimal(p.termo_b) * 100
        r.append(_res("PROP_PERCENTUAL_DIVERGE", abs(razao - p.percentual) <= Decimal("0.01"), ["proporcao"],
                      "Percentual declarado deve igualar novas ÷ base × 100.",
                      f"{razao.quantize(Decimal('0.01'))}%", f"{p.percentual}%"))
    return r


def checar_golden(v: ValidacaoGolden) -> list[RegraResultado]:
    mapa = {
        "NOT_FOUND": "GOLDEN_NAO_ENCONTRADO", "PARTIAL_MISMATCH": "GOLDEN_DIVERGENTE",
        "AMBIGUOUS": "GOLDEN_AMBIGUO",
    }
    r: list[RegraResultado] = []
    campos = ["emissor", "isin", "ticker", "cnpj"]
    for status, regra in mapa.items():
        diverge = [str(c["campo"]) for c in v.comparacoes if c.get("resultado") in {"DIVERGE", "NAO_ENCONTRADO"}]
        if v.status != status:
            obs = None
        elif status == "NOT_FOUND":
            obs = "não constam na base de referência: " + ", ".join(
                f"{c['campo']} {c['aviso']}" for c in v.comparacoes if c.get("aviso")
            )
        else:
            obs = "; ".join(
                f"{c['campo']}: aviso={c.get('aviso')} × base={c.get('golden')}" for c in v.comparacoes
                if c.get("resultado") in {"DIVERGE", "APONTA_PARA_OUTRO_REGISTRO"}
            )
        r.append(_res(
            regra, v.status != status, campos if status != "PARTIAL_MISMATCH" else (diverge or campos),
            SPECS.descricao(regra), observado=obs,
        ))
    if v.registro_golden is not None:
        r.append(_res("GOLDEN_INATIVO", v.registro_golden.get("status") == "ativo", ["isin"],
                      SPECS.descricao("GOLDEN_INATIVO"), observado=v.registro_golden.get("status")))
    return r
