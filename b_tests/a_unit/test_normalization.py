from datetime import date
from decimal import Decimal

from lexis.a_domain.normalization import (
    canonico,
    equivalentes,
    nome_emissor_canonico,
    normalizar,
    parse_classe,
    parse_data,
    parse_decimal,
    parse_percentual,
    parse_proporcao,
)


def test_datas_numericas_e_por_extenso():
    assert parse_data("03/07/2026") == date(2026, 7, 3)
    assert parse_data("28 de maio de 2026") == date(2026, 5, 28)
    assert parse_data("1º de janeiro de 2026") == date(2026, 1, 1)
    assert parse_data("02 de MARÇO de 2026") == date(2026, 3, 2)


def test_data_invalida_ou_ambigua_nao_e_interpretada():
    assert parse_data("31/02/2026") is None
    assert parse_data("29/06/2026 a 28/07/2026") is None  # duas datas: ambíguo
    assert parse_data("A definir (vide aviso complementar)") is None


def test_decimal_brasileiro_preserva_casas():
    v = parse_decimal("R$ 0,4275000000")
    assert v == Decimal("0.4275000000")
    assert v is not None and v.as_tuple().exponent == -10
    assert parse_decimal("R$ 50.000,00") == Decimal("50000.00")
    assert parse_decimal("R$ 7,820000 por ação") == Decimal("7.820000")
    assert parse_decimal("de 10 a 20") is None


def test_percentual_vira_fracao():
    assert parse_percentual("17,5%") == Decimal("0.175")
    assert parse_percentual("alíquota de 10% e 5%") is None


def test_proporcoes():
    g = parse_proporcao("10:1 (dez para uma)")
    assert (g.termo_a, g.termo_b, g.forma) == (10, 1, "RAZAO")
    b = parse_proporcao("1 ação nova para cada 20 ações (5%)")
    assert (b.termo_a, b.termo_b, b.percentual, b.forma) == (1, 20, Decimal("5"), "NOVAS_PARA_CADA")
    e = parse_proporcao("10 (dez) ações existentes para 1 (uma) ação")
    assert (e.termo_a, e.termo_b, e.forma) == (10, 1, "EXISTENTES_PARA")
    # redação padrão citada pelo modelo real no doc 08 (número por extenso entre parênteses)
    x = parse_proporcao("1 (uma) ação nova para cada 20 (vinte) ações")
    assert (x.termo_a, x.termo_b, x.percentual, x.forma) == (1, 20, None, "NOVAS_PARA_CADA")
    assert parse_proporcao("sem proporção") is None


def test_leituras_equivalentes_de_texto_livre_ignoram_quebra_e_ponto_final():
    # caso real do scan (doc 07): as duas leituras citaram a mesma frase, uma com quebra de linha e ponto final
    a = normalizar("observacao_tributaria", "com retenção de IRRF à alíquota de 17,5% sobre o valor bruto")
    b = normalizar("observacao_tributaria", "com retenção de IRRF\nà alíquota de 17,5% sobre o valor bruto.")
    assert equivalentes("observacao_tributaria", a, b)
    c = normalizar("observacao_tributaria", "com retenção de IRRF à alíquota de 15% sobre o valor bruto")
    assert not equivalentes("observacao_tributaria", a, c)  # conteúdo diferente continua divergindo
    # campos normalizados não ganham tolerância: comparam o valor
    assert not equivalentes("valor_bruto", normalizar("valor_bruto", "R$ 0,10"), normalizar("valor_bruto", "R$ 0,1"))


def test_classe():
    assert parse_classe("ação ON") == "ON"
    assert parse_classe("preferencial") == "PN"
    assert parse_classe("ordinária") == "ON"


def test_normalizar_por_campo():
    assert normalizar("isin", " br tieta cnor3 ").repr == "BRTIETACNOR3"
    assert normalizar("data_com", "12/06/2026").repr == "2026-06-12"
    assert normalizar("data_com", "texto sem data") is None
    assert normalizar("aliquota_irrf", "17,5%").repr == "0.175"
    assert normalizar("moeda", "R$").repr == "BRL"


def test_canonico_ignora_acento_caixa_e_espacos():
    assert canonico("  ENERGÉTICA   Vale\ndo Tietê ") == "energetica vale do tiete"
    assert nome_emissor_canonico("Energética Vale do Tietê S.A.") == nome_emissor_canonico("ENERGÉTICA VALE DO TIETÊ S.A.")
