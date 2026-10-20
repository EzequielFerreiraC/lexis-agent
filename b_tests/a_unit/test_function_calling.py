"""Function calling de verdade: o modelo pede a tool, recebe o tool_result e continua (sem rede: cliente falso)."""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from b_tests.conftest import extracao_replay, resposta_tool_use
from lexis.a_domain.models import TipoEvento
from lexis.a_domain.ports import ErroExtracao
from lexis.c_extraction.config import Config
from lexis.c_extraction.recordings import ETAPA_TOOLS, ChamadorComCache, chave_gravacao
from lexis.d_validation.tools import DEFINICOES, args_esperados, orquestrar
from lexis.g_adapters.anthropic_api import BETA_FALLBACK, MAX_TURNOS, ChamadorAnthropic, ExtratorAnthropic
from lexis.g_adapters.local_storage import ArmazenamentoMemoria

DADOS = {
    "isin": "BRBMRDACNPR7", "ticker": "BMRD4", "cnpj": "60.111.222/0001-55", "emissor": "BANCO MERIDIONAL DO BRASIL S.A.",
    "classe_acao": "PN", "data_aprovacao": date(2026, 6, 2), "data_com": date(2026, 6, 16), "data_ex": date(2026, 6, 17),
    "data_pagamento": date(2026, 8, 14), "valor_bruto": Decimal("0.1738420000"), "aliquota_irrf": Decimal("0.175"),
    "valor_liquido": Decimal("0.1434196500"),
}
TOOLS_JCP = ["consultar_golden", "checar_datas", "checar_tributacao"]


class ClienteFalso:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create_beta))
        self.via_beta = []

    def _create(self, **kw):
        self.via_beta.append(False)
        return self._responder(kw)

    def _create_beta(self, **kw):
        self.via_beta.append(True)
        return self._responder(kw)

    def _responder(self, kw):
        # retrato da requisição no momento da chamada (a lista de mensagens cresce depois)
        self.chamadas.append({**kw, "messages": list(kw["messages"])})
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def bloco_tool(nome, args, id_):
    return SimpleNamespace(type="tool_use", name=nome, input=args, id=id_)


def resposta(*blocos, parada="tool_use", ent=100, sai=20, modelo="claude-sonnet-5-5", iteracoes=None):
    return SimpleNamespace(content=list(blocos), stop_reason=parada, model=modelo,
                           usage=SimpleNamespace(input_tokens=ent, output_tokens=sai, iterations=iteracoes))


def texto(t, **kw):
    return resposta(SimpleNamespace(type="text", text=t), parada="end_turn", **kw)


def args_completos(nome, **troca):
    """Como o modelo manda em modo strict: só os campos do schema presentes no registro."""
    esperados = args_esperados(nome, TipoEvento.JCP, DADOS)
    props = DEFINICOES[nome]["input_schema"]["properties"]
    return {k: esperados[k] for k in props if k in esperados} | troca


def pedidos_corretos(prefixo="tu"):
    return [bloco_tool(n, args_completos(n), f"{prefixo}_{i}") for i, n in enumerate(TOOLS_JCP)]


def chamador(cliente, **cfg):
    return ChamadorAnthropic(ExtratorAnthropic(Config(**cfg), cliente=cliente))


# ------------------------------------------------------------------------------------------- loop de tools


def test_modelo_pede_tools_recebe_resultados_e_encerra_com_parecer(golden):
    r1 = resposta(*pedidos_corretos())
    cliente = ClienteFalso([r1, texto("Nenhuma regra falhou.", ent=300, sai=15)])
    v = orquestrar(TipoEvento.JCP, DADOS, golden, chamador(cliente))

    aceitas = [c for c in v.chamadas if c["aceita"]]
    assert [c["tool"] for c in aceitas] == TOOLS_JCP and {c["origem"] for c in aceitas} == {"MODELO"}
    # 1ª requisição: só as tools aplicáveis, em modo strict, sem forçar tool_choice
    primeira = cliente.chamadas[0]
    assert [t["name"] for t in primeira["tools"]] == TOOLS_JCP and all(t["strict"] for t in primeira["tools"])
    assert "tool_choice" not in primeira and "temperature" not in primeira
    assert primeira["messages"][0]["content"].startswith("<registro_")
    # 2ª requisição: o conteúdo do assistente volta intacto e TODOS os tool_result vão numa única mensagem
    segunda = cliente.chamadas[1]["messages"]
    assert segunda[1] == {"role": "assistant", "content": r1.content}
    resultados = segunda[2]["content"]
    assert [r["tool_use_id"] for r in resultados] == ["tu_0", "tu_1", "tu_2"]
    assert not any(r["is_error"] for r in resultados)
    assert any(x["id"] == "TRIB_LIQUIDO_DIVERGE" for x in json.loads(resultados[2]["content"])["regras"])
    # conversa auditável: parecer, encerramento e tokens das duas requisições
    assert v.conversa.parecer == "Nenhuma regra falhou." and v.conversa.encerramento == "end_turn"
    assert (v.conversa.chamada.tokens_entrada, v.conversa.chamada.tokens_saida) == (400, 35)


def test_modelo_corrige_argumento_apos_erro_e_a_chamada_corrigida_e_aceita(golden):
    errado = [bloco_tool("checar_datas", args_completos("checar_datas", data_pagamento="2026-06-20"), "a")]
    corrigido = [bloco_tool("checar_datas", args_completos("checar_datas"), "b")]
    outros = [bloco_tool(n, args_completos(n), n) for n in ("consultar_golden", "checar_tributacao")]
    cliente = ClienteFalso([resposta(*errado, *outros), resposta(*corrigido), texto("ok")])
    v = orquestrar(TipoEvento.JCP, DADOS, golden, chamador(cliente))

    rejeitada = next(c for c in v.chamadas if not c["aceita"])
    assert rejeitada["motivo"] == "ARGS_DIVERGEM_DO_EXTRAIDO"
    datas = next(c for c in v.chamadas if c["tool"] == "checar_datas" and c["aceita"])
    assert datas["origem"] == "MODELO"  # foi o modelo, depois de corrigir, e não o orquestrador
    erro = cliente.chamadas[1]["messages"][2]["content"][0]
    assert erro["is_error"] and json.loads(erro["content"])["campos_divergentes"] == ["data_pagamento"]
    assert len(v.conversa.turnos) == 2


def test_resposta_truncada_em_max_tokens_nao_executa_a_tool(golden):
    cliente = ClienteFalso([resposta(*pedidos_corretos(), parada="max_tokens")])
    v = orquestrar(TipoEvento.JCP, DADOS, golden, chamador(cliente))
    assert v.conversa.encerramento == "max_tokens" and v.conversa.turnos == []
    assert {c["origem"] for c in v.chamadas if c["aceita"]} == {"ORQUESTRADOR"}


def test_recusa_do_modelo_vira_codigo_e_a_validacao_segue(golden):
    recusa = resposta(parada="refusal", ent=50, sai=2)
    recusa.stop_details = SimpleNamespace(category="cyber")
    v = orquestrar(TipoEvento.JCP, DADOS, golden, chamador(ClienteFalso([recusa])))
    assert v.conversa.encerramento == "ERRO:RECUSA_DO_MODELO" and v.conversa.chamada.tokens_entrada == 50
    assert any(c.get("motivo") == "RECUSA_DO_MODELO" for c in v.chamadas)
    assert sum(c["aceita"] for c in v.chamadas) == 3


def test_loop_tem_limite_de_turnos(golden):
    repetida = [resposta(bloco_tool("checar_datas", args_completos("checar_datas", data_com="x"), f"t{i}"))
                for i in range(MAX_TURNOS)]
    cliente = ClienteFalso(repetida)
    v = orquestrar(TipoEvento.JCP, DADOS, golden, chamador(cliente))
    assert v.conversa.encerramento == "LIMITE_DE_TURNOS" and len(cliente.chamadas) == MAX_TURNOS


def test_orcamento_estourado_no_meio_da_conversa_nao_derruba_a_validacao(golden):
    cliente = ClienteFalso([resposta(*pedidos_corretos(), ent=90, sai=20), texto("x")])
    v = orquestrar(TipoEvento.JCP, DADOS, golden, chamador(cliente, orcamento_tokens=100))
    assert v.conversa.encerramento == "ERRO:ORCAMENTO_EXCEDIDO"
    assert [c["origem"] for c in v.chamadas if c["aceita"]] == ["MODELO"] * 3  # o 1º turno já tinha valido


# ------------------------------------------------------------------------------------- gravação e replay


def test_conversa_gravada_e_reproduzida_sem_cliente_com_as_tools_pedidas_pelo_modelo(golden):
    arm = ArmazenamentoMemoria()
    cliente = ClienteFalso([resposta(*pedidos_corretos()), texto("Nenhuma regra falhou.")])
    ao_vivo = ChamadorComCache(chamador(cliente), arm, "sha", "live", "x.pdf")
    orquestrar(TipoEvento.JCP, DADOS, golden, ao_vivo)
    gravado = json.loads(arm.ler(chave_gravacao("sha", ETAPA_TOOLS)))
    assert gravado["origem"] == "API" and gravado["pedido_sha"] and gravado["modelo"] == "claude-sonnet-5-5"
    assert gravado["conteudo"]["parecer"] == "Nenhuma regra falhou."

    replay = ChamadorComCache(None, arm, "sha", "replay")
    v = orquestrar(TipoEvento.JCP, DADOS, golden, replay)
    assert [c["origem"] for c in v.chamadas if c["aceita"]] == ["MODELO"] * 3
    assert replay.ultima.chamada.origem == "CACHE" and replay.ultima.avisos == []
    assert len(cliente.chamadas) == 2  # o replay não chamou o modelo


def test_replay_de_registro_diferente_nao_reaproveita_a_conversa(golden):
    arm = ArmazenamentoMemoria()
    ao_vivo = ChamadorComCache(chamador(ClienteFalso([resposta(*pedidos_corretos()), texto("ok")])), arm, "sha", "live")
    orquestrar(TipoEvento.JCP, DADOS, golden, ao_vivo)
    outro = dict(DADOS, valor_liquido=Decimal("0.1434196999"))
    v = orquestrar(TipoEvento.JCP, outro, golden, ChamadorComCache(None, arm, "sha", "replay"))
    assert any(c.get("motivo") == "GRAVACAO_DESATUALIZADA" for c in v.chamadas)
    assert {c["origem"] for c in v.chamadas if c["aceita"]} == {"ORQUESTRADOR"}


def test_resultado_que_mudou_desde_a_gravacao_gera_aviso(golden):
    arm = ArmazenamentoMemoria()
    ao_vivo = ChamadorComCache(chamador(ClienteFalso([resposta(*pedidos_corretos()), texto("ok")])), arm, "sha", "live")
    orquestrar(TipoEvento.JCP, DADOS, golden, ao_vivo)
    chave = chave_gravacao("sha", ETAPA_TOOLS)
    gravado = json.loads(arm.ler(chave))
    gravado["conteudo"]["turnos"][0]["chamadas"][1]["resultado"] = {"regras": []}
    arm.gravar(chave, json.dumps(gravado).encode())
    replay = ChamadorComCache(None, arm, "sha", "replay")
    orquestrar(TipoEvento.JCP, DADOS, golden, replay)
    assert replay.ultima.avisos and "checar_datas" in replay.ultima.avisos[0]


def test_conversa_interrompida_por_erro_nao_e_gravada(golden):
    arm = ArmazenamentoMemoria()
    recusa = resposta(parada="refusal")
    recusa.stop_details = None
    orquestrar(TipoEvento.JCP, DADOS, golden, ChamadorComCache(chamador(ClienteFalso([recusa])), arm, "sha", "live"))
    assert arm.listar() == []


# ---------------------------------------------------------------------------- cliente: fallback e erros


def test_fallback_do_servidor_usa_beta_e_registra_quem_respondeu():
    iteracoes = [SimpleNamespace(type="message"), SimpleNamespace(type="fallback_message")]
    r = resposta_tool_use(extracao_replay("01_energetica_vale_tiete_dividendo").model_dump(mode="json"))
    r.model, r.stop_reason = "claude-opus-4-8", "tool_use"
    r.usage.iterations = iteracoes
    cliente = ClienteFalso([r])
    _, meta = ExtratorAnthropic(Config(), cliente=cliente).extrair_texto("t")
    kw = cliente.chamadas[0]
    assert cliente.via_beta == [True] and kw["betas"] == [BETA_FALLBACK] and kw["fallbacks"] == "default"
    assert kw["output_config"] == {"effort": "medium"}
    assert meta.modelo == "claude-opus-4-8" and "fallback" in meta.aviso


def test_sem_fallback_usa_a_api_estavel():
    cliente = ClienteFalso([texto("transcrição")])
    ExtratorAnthropic(Config(fallbacks="off"), cliente=cliente).transcrever(b"png")
    assert cliente.via_beta == [False] and "fallbacks" not in cliente.chamadas[0]


def _erro_http(classe, status):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return classe(message="detalhe sensível sk-ant-xyz", response=httpx.Response(status, request=req), body=None)


@pytest.mark.parametrize(("classe", "status", "codigo"), [
    (anthropic.AuthenticationError, 401, "CREDENCIAL_RECUSADA"),
    (anthropic.BadRequestError, 400, "REQUISICAO_REJEITADA"),
    (anthropic.RateLimitError, 429, "FALHA_PROVEDOR"),
    (anthropic.InternalServerError, 500, "FALHA_PROVEDOR"),
])
def test_erros_do_provedor_sao_classificados_sem_vazar_a_mensagem(classe, status, codigo):
    with pytest.raises(ErroExtracao) as e:
        ExtratorAnthropic(Config(), cliente=ClienteFalso([_erro_http(classe, status)])).transcrever(b"png")
    assert e.value.codigo == codigo and f"HTTP {status}" in e.value.detalhe and "sk-ant" not in str(e.value)


def test_reparo_de_tool_use_invalido_responde_com_tool_result():
    ruim = extracao_replay("01_energetica_vale_tiete_dividendo").model_dump(mode="json")
    ruim["campos"]["campo_inventado"] = {"texto": "x", "pagina": 1, "situacao": "PRESENTE"}
    boa = extracao_replay("01_energetica_vale_tiete_dividendo").model_dump(mode="json")
    cliente = ClienteFalso([resposta_tool_use(ruim), resposta_tool_use(boa)])
    _, meta = ExtratorAnthropic(Config(), cliente=cliente).extrair_texto("t")
    volta = cliente.chamadas[1]["messages"][-1]["content"][0]
    assert meta.reparos == 1 and volta["type"] == "tool_result" and volta["is_error"] is True
    assert "1 erro(s): campos" in volta["content"] and "campo_inventado" in volta["content"]  # onde, não o valor


def test_configuracao_rejeita_valores_invalidos():
    with pytest.raises(ValueError):
        Config(esforco="altissimo")
    with pytest.raises(ValueError):
        Config(fallbacks="sim")
