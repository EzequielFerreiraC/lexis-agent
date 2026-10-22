"""Testes de contrato: schema de saída versionado, estados estáveis e catálogo de regras coerente."""

import json

from b_tests.conftest import DOCS
from lexis.a_domain.models import SCHEMA_VERSION, Decisao, EstadoCampo, Severidade, TipoAcao
from lexis.a_domain.specs import SPECS
from lexis.d_validation.tools import DEFINICOES
from lexis.e_decision.checklists import ACAO_POR_REGRA
from lexis.g_adapters.local_execution import processar_documento
from lexis.h_interfaces import contracts


def test_schema_publicado_em_e_docs_acompanha_o_modelo():
    publicado = contracts.DESTINO_SCHEMA.read_text(encoding="utf-8")
    assert publicado == contracts.schema_atual(), "contrato mudou: rode `lexis contratos` (e suba a versão)"


def test_estados_e_acoes_sao_um_contrato_estavel_para_consumidores():
    assert {d.value for d in Decisao} == {"APROVADO_AUTO", "AGUARDA_EMISSOR", "REVISAO_HUMANA", "FALHA_PROCESSAMENTO"}
    assert {e.value for e in EstadoCampo} == {"EXTRAIDO", "NAO_APLICAVEL", "AUSENTE", "PENDENTE", "INCERTO"}
    assert SCHEMA_VERSION == "1.1"  # 1.1: decisao.para_aprovar (aditivo)


def test_registro_real_tem_todas_as_secoes_obrigatorias_do_contrato(ctx):
    r = processar_documento(DOCS / "02_banco_meridional_jcp.pdf", ctx, "t").model_dump(mode="json")
    esperado = {"schema_version", "run_id", "documento", "versoes", "decisao", "evento", "campos",
                "validacao_golden", "regras", "fichas_conferencia", "auditoria"}
    assert set(r) == esperado
    assert set(r["campos"]) >= {"tipo_evento", *SPECS.campos}


def test_catalogo_de_regras_e_consistente_com_o_codigo():
    assert {r["severidade"] for r in SPECS.regras.values()} <= {s.value for s in Severidade}
    assert set(ACAO_POR_REGRA) <= set(SPECS.regras), "ação mapeada para regra inexistente"
    assert set(ACAO_POR_REGRA.values()) <= set(TipoAcao)
    for tipo in SPECS.tipos.values():
        assert set(tipo["aplicabilidade"]) == set(SPECS.campos), "matriz de aplicabilidade incompleta"
        assert set(tipo["criticos"]) <= set(SPECS.campos)


def test_contrato_das_tools_e_estavel():
    assert sorted(DEFINICOES["consultar_golden"]["input_schema"]["properties"]) == [
        "classe_acao", "cnpj", "emissor", "isin", "ticker"]
    assert json.dumps(DEFINICOES["checar_datas"]["input_schema"]["additionalProperties"]) == "false"
