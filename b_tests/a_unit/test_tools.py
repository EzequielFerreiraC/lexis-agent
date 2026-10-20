from datetime import date
from decimal import Decimal

import pytest

from lexis.a_domain.models import TipoEvento
from lexis.a_domain.ports import ConversaTools, ErroExtracao
from lexis.d_validation.tools import DEFINICOES, args_esperados, executar_tool, orquestrar, tools_aplicaveis

DADOS = {
    "isin": "BRBMRDACNPR7", "ticker": "BMRD4", "cnpj": "60.111.222/0001-55", "emissor": "BANCO MERIDIONAL DO BRASIL S.A.",
    "classe_acao": "PN", "data_aprovacao": date(2026, 6, 2), "data_com": date(2026, 6, 16), "data_ex": date(2026, 6, 17),
    "data_pagamento": date(2026, 8, 14), "valor_bruto": Decimal("0.1738420000"), "aliquota_irrf": Decimal("0.175"),
    "valor_liquido": Decimal("0.1434196500"),
}


class ChamadorFixo:
    """Simula o modelo pedindo tools num único turno; guarda o que `atender` devolveu (o tool_result)."""

    def __init__(self, chamadas):
        self.chamadas = chamadas
        self.respostas = []

    def conduzir(self, pedido, atender):
        self.pedido = pedido
        self.respostas = [atender(nome, args) for nome, args in self.chamadas]
        return ConversaTools(turnos=[{"chamadas": []}], encerramento="end_turn")


class ChamadorQuebrado:
    def conduzir(self, pedido, atender):
        raise TimeoutError("provedor fora")


def test_tools_aplicaveis_por_tipo():
    assert tools_aplicaveis(TipoEvento.JCP, DADOS) == ["consultar_golden", "checar_datas", "checar_tributacao"]
    assert "checar_proporcao" in tools_aplicaveis(TipoEvento.GRUPAMENTO, {})


def test_sem_chamador_o_orquestrador_executa_todas_as_obrigatorias(golden):
    v = orquestrar(TipoEvento.JCP, DADOS, golden, None)
    assert [c["tool"] for c in v.chamadas] == ["consultar_golden", "checar_datas", "checar_tributacao"]
    assert {c["origem"] for c in v.chamadas} == {"ORQUESTRADOR"}
    assert v.golden is not None and v.golden.status == "MATCH"


def test_chamada_do_modelo_com_args_corretos_e_aceita(golden):
    args = args_esperados("checar_datas", TipoEvento.JCP, DADOS)
    v = orquestrar(TipoEvento.JCP, DADOS, golden, ChamadorFixo([("checar_datas", args)]))
    c = next(c for c in v.chamadas if c["tool"] == "checar_datas")
    assert c["origem"] == "MODELO" and c["aceita"]
    assert {c["tool"] for c in v.chamadas if c["aceita"]} == {"consultar_golden", "checar_datas", "checar_tributacao"}


def test_modelo_nao_valida_valores_inventados(golden):
    args = args_esperados("checar_datas", TipoEvento.JCP, DADOS) | {"data_pagamento": "2026-06-20"}
    v = orquestrar(TipoEvento.JCP, DADOS, golden, ChamadorFixo([("checar_datas", args)]))
    rejeitada = next(c for c in v.chamadas if c.get("motivo") == "ARGS_DIVERGEM_DO_EXTRAIDO")
    assert not rejeitada["aceita"]
    # o orquestrador executou a tool com os valores REAIS
    executada = next(c for c in v.chamadas if c["tool"] == "checar_datas" and c["aceita"])
    assert executada["origem"] == "ORQUESTRADOR" and executada["argumentos"]["data_pagamento"] == "2026-08-14"


def test_tool_fora_da_allow_list_e_rejeitada(golden):
    v = orquestrar(TipoEvento.JCP, DADOS, golden, ChamadorFixo([("executar_shell", {"cmd": "ls"})]))
    assert any(c.get("motivo") == "FORA_DA_ALLOW_LIST" and not c["aceita"] for c in v.chamadas)
    with pytest.raises(KeyError):
        executar_tool("executar_shell", {}, golden)


def test_chamada_duplicada_e_nao_aplicavel_sao_rejeitadas(golden):
    a = args_esperados("checar_datas", TipoEvento.JCP, DADOS)
    v = orquestrar(TipoEvento.JCP, DADOS, golden,
                   ChamadorFixo([("checar_datas", a), ("checar_datas", a), ("checar_proporcao", {"tipo_evento": "JCP"})]))
    motivos = [c.get("motivo") for c in v.chamadas if not c["aceita"]]
    assert "DUPLICADA" in motivos and "NAO_APLICAVEL_AO_TIPO" in motivos


def test_falha_do_provedor_nao_derruba_a_validacao(golden):
    v = orquestrar(TipoEvento.JCP, DADOS, golden, ChamadorQuebrado())
    assert sum(c["aceita"] for c in v.chamadas) == 3
    assert any("FALHA_PROVEDOR" in str(c.get("motivo")) for c in v.chamadas)


def test_veredito_vem_da_tool_e_nao_do_modelo(golden):
    ruim = dict(DADOS, valor_liquido=Decimal("0.1434196999"))
    v = orquestrar(TipoEvento.JCP, ruim, golden, None)
    assert any(r.id == "TRIB_LIQUIDO_DIVERGE" and r.resultado == "FALHA" for r in v.regras)


def test_definicoes_sao_somente_leitura_fechadas_e_strict():
    for d in DEFINICOES.values():
        esquema = d["input_schema"]
        assert esquema["additionalProperties"] is False and d["strict"] is True
        assert all(p == {"type": "string"} for p in esquema["properties"].values())  # sem união com null
    assert set(DEFINICOES) == {"consultar_golden", "checar_datas", "checar_tributacao", "checar_proporcao"}
    # limites do modo strict por requisição: <= 24 parâmetros opcionais mesmo com as 4 tools oferecidas
    opcionais = sum(len(d["input_schema"]["properties"]) - len(d["input_schema"]["required"]) for d in DEFINICOES.values())
    assert opcionais <= 24


def test_argumentos_esperados_seguem_a_ordem_do_schema():
    # regressão real (doc 08): com strict, o modelo emite as propriedades na ordem do schema; registro em outra
    # ordem fez o modelo omitir `percentual_declarado` em todas as tentativas
    from lexis.a_domain.normalization import Proporcao

    dados = dict(DADOS, proporcao=Proporcao(1, 20, Decimal("5"), "NOVAS_PARA_CADA"))
    for nome in DEFINICOES:
        args = args_esperados(nome, TipoEvento.BONIFICACAO, dados)
        ordem = [k for k in DEFINICOES[nome]["input_schema"]["properties"] if k in args]
        assert list(args) == ordem, nome


def test_modelo_recebe_resultado_da_tool_e_so_as_tools_aplicaveis(golden):
    args = args_esperados("checar_tributacao", TipoEvento.JCP, DADOS)
    ch = ChamadorFixo([("checar_tributacao", args)])
    orquestrar(TipoEvento.JCP, DADOS, golden, ch)
    assert ch.pedido.nomes == ["consultar_golden", "checar_datas", "checar_tributacao"]  # proporção não é oferecida
    conteudo, erro = ch.respostas[0]
    assert not erro and any(r["id"] == "TRIB_LIQUIDO_DIVERGE" and r["resultado"] == "OK" for r in conteudo["regras"])


def test_erro_devolvido_ao_modelo_aponta_o_campo_sem_revelar_o_valor(golden):
    args = args_esperados("checar_datas", TipoEvento.JCP, DADOS) | {"data_pagamento": "2026-06-20"}
    ch = ChamadorFixo([("checar_datas", args)])
    orquestrar(TipoEvento.JCP, DADOS, golden, ch)
    conteudo, erro = ch.respostas[0]
    assert erro and conteudo == {"erro": "ARGS_DIVERGEM_DO_EXTRAIDO", "campos_divergentes": ["data_pagamento"]}
    assert "2026-08-14" not in str(conteudo)


def test_falha_registrada_pelo_chamador_aparece_na_auditoria(golden):
    class ChamadorSemGravacao:
        def conduzir(self, pedido, atender):
            raise ErroExtracao("GRAVACAO_AUSENTE", "sha/validacao_tools.json")

    v = orquestrar(TipoEvento.JCP, DADOS, golden, ChamadorSemGravacao())
    assert {"tool": None, "origem": "MODELO", "aceita": False, "motivo": "GRAVACAO_AUSENTE"} in v.chamadas
    assert sum(c["aceita"] for c in v.chamadas) == 3  # o orquestrador cobriu tudo
