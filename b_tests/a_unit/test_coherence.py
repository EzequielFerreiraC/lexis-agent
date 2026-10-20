from datetime import date
from decimal import Decimal

from lexis.a_domain.models import TipoEvento
from lexis.a_domain.normalization import Proporcao
from lexis.d_validation import coherence as rules


def _falhas(rs):
    return {r.id for r in rs if r.resultado == "FALHA"}


def _por_id(rs, id_):
    return next(r for r in rs if r.id == id_)


def test_datas_coerentes_nao_falham():
    d = {"data_aprovacao": date(2026, 5, 28), "data_com": date(2026, 6, 12), "data_ex": date(2026, 6, 15),
         "data_pagamento": date(2026, 7, 3)}
    assert _falhas(rules.checar_datas(TipoEvento.DIVIDENDO, d)) == set()


def test_pagamento_antes_da_data_com_e_ex_falha():  # caso do doc 05
    d = {"data_aprovacao": date(2026, 6, 1), "data_com": date(2026, 7, 15), "data_ex": date(2026, 7, 16),
         "data_pagamento": date(2026, 7, 10)}
    assert {"DATAS_PAGAMENTO_ANTES_DA_COM", "DATAS_PAGAMENTO_ANTES_DA_EX"} <= _falhas(rules.checar_datas(TipoEvento.DIVIDENDO, d))


def test_ex_igual_ou_anterior_a_com_falha():
    d = {"data_com": date(2026, 6, 12), "data_ex": date(2026, 6, 12)}
    assert "DATAS_EX_NAO_POSTERIOR_A_COM" in _falhas(rules.checar_datas(TipoEvento.DIVIDENDO, d))


def test_pagamento_nao_e_avaliado_em_grupamento():
    d = {"data_com": date(2026, 6, 26), "data_ex": date(2026, 6, 29)}
    ids = {r.id for r in rules.checar_datas(TipoEvento.GRUPAMENTO, d)}
    assert "DATAS_PAGAMENTO_ANTES_DA_COM" not in ids


def test_aprovacao_em_fim_de_semana_e_so_informativa():
    r = rules.checar_datas(TipoEvento.GRUPAMENTO, {"data_aprovacao": date(2026, 5, 30)})
    regra = _por_id(r, "DATA_APROVACAO_FIM_DE_SEMANA")
    assert regra.resultado == "FALHA" and regra.severidade.value == "INFO"


def test_ex_em_dia_nao_util_seguinte_e_aviso():
    d = {"data_com": date(2026, 6, 12), "data_ex": date(2026, 6, 16)}  # sexta -> terça
    assert _por_id(rules.checar_datas(TipoEvento.DIVIDENDO, d), "DATAS_EX_NAO_E_DIA_UTIL_SEGUINTE").resultado == "FALHA"


def test_data_muito_distante_da_aprovacao_sugere_erro_de_ano():
    d = {"data_aprovacao": date(2026, 6, 6), "data_com": date(2028, 6, 22), "data_ex": date(2028, 6, 23)}
    assert "DATAS_FORA_DA_FAIXA" in _falhas(rules.checar_datas(TipoEvento.JCP, d))


def test_liquido_confere_com_aliquota_do_proprio_aviso():
    d = {"valor_bruto": Decimal("0.1738420000"), "aliquota_irrf": Decimal("0.175"), "valor_liquido": Decimal("0.1434196500")}
    assert _falhas(rules.checar_tributacao(TipoEvento.JCP, d)) == set()


def test_liquido_com_ultimo_digito_trocado_e_detectado():
    # regressão: a tolerância de 1 ULP deixava passar uma troca no último dígito
    d = {"valor_bruto": Decimal("0.1738420000"), "aliquota_irrf": Decimal("0.175"), "valor_liquido": Decimal("0.1434196501")}
    assert "TRIB_LIQUIDO_DIVERGE" in _falhas(rules.checar_tributacao(TipoEvento.JCP, d))


def test_liquido_arredondado_dentro_de_meia_unidade_passa():
    bruto, aliq = Decimal("0.1000000001"), Decimal("0.175")  # esperado 0.08250000008...
    d = {"valor_bruto": bruto, "aliquota_irrf": aliq, "valor_liquido": Decimal("0.0825000001")}
    assert "TRIB_LIQUIDO_DIVERGE" not in _falhas(rules.checar_tributacao(TipoEvento.JCP, d))


def test_aliquota_nao_e_fixa():
    d = {"valor_bruto": Decimal("1.0000000000"), "aliquota_irrf": Decimal("0.15"), "valor_liquido": Decimal("0.8500000000")}
    assert _falhas(rules.checar_tributacao(TipoEvento.JCP, d)) == set()


def test_liquido_sem_aliquota_nao_e_verificavel():
    d = {"valor_bruto": Decimal("1.00"), "valor_liquido": Decimal("0.80")}
    assert "TRIB_LIQUIDO_SEM_ALIQUOTA" in _falhas(rules.checar_tributacao(TipoEvento.JCP, d))


def test_dividendo_com_retencao_por_acao_e_inconsistente():  # substância de JCP
    d = {"valor_bruto": Decimal("1.00"), "valor_liquido": Decimal("0.825")}
    assert "TRIB_DIVIDENDO_COM_RETENCAO" in _falhas(rules.checar_tributacao(TipoEvento.DIVIDENDO, d))


def test_valor_nao_positivo():
    assert "VALOR_NAO_POSITIVO" in _falhas(rules.checar_tributacao(TipoEvento.DIVIDENDO, {"valor_bruto": Decimal("0")}))


def test_grupamento_precisa_reduzir_quantidade():
    ok = rules.checar_proporcao(TipoEvento.GRUPAMENTO, {"proporcao": Proporcao(10, 1, None, "RAZAO")})
    ruim = rules.checar_proporcao(TipoEvento.GRUPAMENTO, {"proporcao": Proporcao(1, 10, None, "RAZAO")})
    assert _falhas(ok) == set()
    assert "PROP_SENTIDO_INCOMPATIVEL" in _falhas(ruim)


def test_bonificacao_percentual_deve_bater_com_a_razao():
    ok = rules.checar_proporcao(TipoEvento.BONIFICACAO, {"proporcao": Proporcao(1, 20, Decimal("5"), "NOVAS_PARA_CADA")})
    ruim = rules.checar_proporcao(TipoEvento.BONIFICACAO, {"proporcao": Proporcao(1, 20, Decimal("10"), "NOVAS_PARA_CADA")})
    assert _falhas(ok) == set()
    assert "PROP_PERCENTUAL_DIVERGE" in _falhas(ruim)


def test_formatos():
    ruim = rules.checar_formatos({"isin": "BR123", "ticker": "ABC1", "cnpj": "123"})
    assert _falhas(ruim) == {"FORMATO_ISIN", "FORMATO_TICKER", "FORMATO_CNPJ"}
    assert _falhas(rules.checar_formatos({"isin": "BRTIETACNOR3", "ticker": "TIET3", "cnpj": "12.345.678/0001-90"})) == set()
