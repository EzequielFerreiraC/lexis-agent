import pytest

from b_tests.conftest import GOLDEN_CSV
from lexis.d_validation.reference_base import Golden
from lexis.g_adapters.local_execution import carregar_golden


@pytest.fixture(scope="module")
def g() -> Golden:
    return carregar_golden(GOLDEN_CSV)


def test_match_completo(g):
    v = g.consultar(isin="BRTIETACNOR3", ticker="TIET3", cnpj="12.345.678/0001-90",
                    emissor="ENERGÉTICA VALE DO TIETÊ S.A.", classe="ON")
    assert v.status == "MATCH"


def test_classe_diferente_da_base_e_divergencia(g):
    v = g.consultar(isin="BRTIETACNOR3", ticker="TIET3", cnpj=None, emissor=None, classe="PN")
    assert v.status == "PARTIAL_MISMATCH"
    assert any(c["campo"] == "classe_acao" and c["resultado"] == "DIVERGE" for c in v.comparacoes)


def test_isin_inexistente_com_ticker_valido_diverge(g):
    v = g.consultar(isin="BRZZZZACNOR9", ticker="TIET3", cnpj=None, emissor=None, classe=None)
    assert v.status == "PARTIAL_MISMATCH"


def test_identificadores_de_emissores_diferentes_sao_ambiguos(g):
    v = g.consultar(isin="BRTIETACNOR3", ticker="BMRD4", cnpj=None, emissor=None, classe=None)
    assert v.status == "AMBIGUOUS"


def test_emissor_fora_da_base(g):
    v = g.consultar(isin="BRCNHZACNOR5", ticker="CNHZ3", cnpj="09.888.999/0001-21",
                    emissor="CONSTRUTORA HORIZONTE S.A.", classe=None)
    assert v.status == "NOT_FOUND" and v.registro_golden is None


def test_nome_parecido_so_sugere_nunca_confirma(g):
    v = g.consultar(isin="BRXXXXACNOR1", ticker="ZZZZ3", cnpj=None, emissor="Energética Vale do Tietê SA", classe=None)
    assert v.status == "NOT_FOUND"
    assert v.sugestao_por_nome and v.sugestao_por_nome["ticker"] == "TIET3"
    assert "não confirma" in v.sugestao_por_nome["uso"]


def test_sem_sugestao_quando_nome_muito_diferente(g):
    assert g.consultar(isin=None, ticker=None, cnpj=None, emissor="Construtora Horizonte S.A.", classe=None).sugestao_por_nome is None


def test_base_nao_tem_duplicatas_nem_inativos(g):
    assert len({r.isin for r in g.registros}) == len(g.registros) == 12
    assert all(r.status == "ativo" for r in g.registros)


_DUAS_CLASSES = b"""emissor,cnpj,isin,ticker,classe,segmento_listagem,status
X S.A.,11.111.111/0001-11,BRXXXXACNOR1,XXXX3,ON,NM,ativo
X S.A.,11.111.111/0001-11,BRXXXXACNPR8,XXXX4,PN,NM,ativo
Y S.A.,22.222.222/0001-22,BRYYYYACNOR5,YYYY3,ON,NM,ativo
"""


@pytest.mark.parametrize("isin,ticker,classe", [("BRXXXXACNOR1", "XXXX3", "ON"), ("BRXXXXACNPR8", "XXXX4", "PN")])
def test_emissor_com_duas_classes_no_mesmo_cnpj_casa_cada_classe(isin, ticker, classe):
    g = Golden.de_bytes(_DUAS_CLASSES)
    v = g.consultar(isin=isin, ticker=ticker, cnpj="11.111.111/0001-11", emissor="X S.A.", classe=classe)
    assert v.status == "MATCH" and v.registro_golden and v.registro_golden["isin"] == isin


def test_cnpj_de_varias_classes_sem_isin_nem_ticker_e_ambiguo():
    g = Golden.de_bytes(_DUAS_CLASSES)
    assert g.consultar(isin=None, ticker=None, cnpj="11.111.111/0001-11", emissor="X S.A.", classe=None).status == "AMBIGUOUS"


def test_cnpj_de_outro_emissor_continua_ambiguo():
    g = Golden.de_bytes(_DUAS_CLASSES)
    v = g.consultar(isin="BRYYYYACNOR5", ticker="YYYY3", cnpj="11.111.111/0001-11", emissor="Y S.A.", classe="ON")
    assert v.status == "AMBIGUOUS"
