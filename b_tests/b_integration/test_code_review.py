"""Regressões dos achados da revisão de código (orçamento, falhas transitórias, circuito, custo, colisões)."""

import json
from types import SimpleNamespace

import pytest

from b_tests.aws_fakes import S3Falso
from b_tests.conftest import DOCS, ExtratorFalso, extracao_replay, resposta_tool_use
from lexis.a_domain.models import Decisao
from lexis.a_domain.ports import ErroExtracao
from lexis.c_extraction.config import Config
from lexis.c_extraction.costs import estimar_custo_usd
from lexis.f_application.batch import chave_registro, processar_lote
from lexis.f_application.pipeline import Contexto, processar_conteudo
from lexis.g_adapters.ambiente import config_do_ambiente
from lexis.g_adapters.anthropic_api import ExtratorAnthropic, chamador_anthropic
from lexis.g_adapters.local_storage import ArmazenamentoMemoria
from lexis.g_adapters.local_trail import TrilhaMemoria
from lexis.h_interfaces.aws_lambda import ConfiguracaoInvalida, construir_contexto, handler

STEM = "01_energetica_vale_tiete_dividendo"
PDF01 = (DOCS / f"{STEM}.pdf").read_bytes()


class ClienteFalso:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=self.messages)  # caminho usado com `fallbacks` ligado

    def _create(self, **kw):
        self.chamadas.append(kw)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def com_uso(resp, entrada, saida):
    resp.usage = SimpleNamespace(input_tokens=entrada, output_tokens=saida)
    return resp


def valida():
    return extracao_replay(STEM).model_dump(mode="json")


# --- 1. orçamento de tokens não acumula entre invocações de uma instância "quente" ---------------------------


def test_orcamento_de_tokens_reinicia_a_cada_execucao(golden):
    # cada documento gasta 150 tokens (extração 100 + tools 50); o orçamento de 150 cabe exatamente um por execução
    cliente = ClienteFalso([com_uso(resposta_tool_use(valida()), 80, 20), com_uso(SimpleNamespace(content=[]), 40, 10)] * 3)
    cfg = Config(orcamento_tokens=150)
    ctx = Contexto(golden=golden, modo="live", cfg=cfg, gravacoes=ArmazenamentoMemoria(), usar_ocr=False,
                   cliente_factory=lambda: ExtratorAnthropic(cfg, cliente=cliente),
                   chamador_factory=chamador_anthropic)
    for _ in range(3):  # 3 "invocações" na mesma instância: cada uma tem o orçamento inteiro
        ctx.reiniciar()
        ctx.gravacoes = ArmazenamentoMemoria()  # sem cache, para forçar chamada
        assert processar_conteudo("a.pdf", PDF01, ctx, "r").decisao.estado is not Decisao.FALHA_PROCESSAMENTO


def test_sem_reiniciar_o_orcamento_acumula_e_estoura(golden):
    cliente = ClienteFalso([com_uso(resposta_tool_use(valida()), 80, 20), com_uso(SimpleNamespace(content=[]), 40, 10)] * 2)
    cfg = Config(orcamento_tokens=150)
    ctx = Contexto(golden=golden, modo="live", cfg=cfg, gravacoes=ArmazenamentoMemoria(), usar_ocr=False,
                   cliente_factory=lambda: ExtratorAnthropic(cfg, cliente=cliente),
                   chamador_factory=chamador_anthropic)
    assert processar_conteudo("a.pdf", PDF01, ctx, "r").decisao.estado is not Decisao.FALHA_PROCESSAMENTO
    ctx.gravacoes = ArmazenamentoMemoria()
    segundo = processar_conteudo("a.pdf", PDF01, ctx, "r")
    assert segundo.decisao.motivos[0].codigo == "ORCAMENTO_EXCEDIDO"


# --- 2. falha transitória não vira resultado final em execução orientada a fila -------------------------------


class ExtratorQuebrado(ExtratorFalso):
    def __init__(self, erro):
        super().__init__(extracao_replay(STEM))
        self.erro = erro

    def extrair_texto(self, texto, etapa="extracao"):
        raise self.erro


def ctx_com(golden, extrator):
    return Contexto(golden=golden, modo="live", cfg=Config(), gravacoes=ArmazenamentoMemoria(), usar_ocr=False,
                    cliente_factory=lambda: extrator)


def test_falha_de_provedor_e_propagada_quando_orientado_a_fila(golden):
    ctx = ctx_com(golden, ExtratorQuebrado(ErroExtracao("FALHA_PROVEDOR", "RateLimitError")))
    with pytest.raises(ErroExtracao):
        processar_conteudo("a.pdf", PDF01, ctx, "r", propagar_transitorios=True)
    registro = processar_conteudo("a.pdf", PDF01, ctx, "r")  # modo lote/CLI: registro explícito
    assert registro.decisao.motivos[0].codigo == "FALHA_PROVEDOR"


def test_falha_deterministica_continua_virando_registro_mesmo_em_modo_fila(golden):
    ctx = ctx_com(golden, ExtratorQuebrado(ErroExtracao("SAIDA_FORA_DO_CONTRATO", "x", tokens_entrada=7, tokens_saida=3)))
    r = processar_conteudo("a.pdf", PDF01, ctx, "r", propagar_transitorios=True)
    assert r.decisao.motivos[0].codigo == "SAIDA_FORA_DO_CONTRATO" and r.auditoria["tokens_entrada"] == 7


def test_erro_inesperado_informa_onde_sem_vazar_a_mensagem(golden):
    segredo = "TEXTO-SENSIVEL-DO-DOCUMENTO"
    ctx = ctx_com(golden, ExtratorQuebrado(RuntimeError(segredo)))
    r = processar_conteudo("a.pdf", PDF01, ctx, "r")
    assert r.decisao.motivos[0].codigo == "ERRO_INESPERADO"
    assert r.auditoria["erro"]["detalhe"] == "RuntimeError" and r.auditoria["onde"]
    assert segredo not in json.dumps(r.model_dump(mode="json"))


ENV = {"LEXIS_BUCKET_ENTRADA": "e", "LEXIS_BUCKET_SAIDA": "s", "LEXIS_BUCKET_REFERENCIA": "r",
       "LEXIS_CHAVE_GOLDEN": "g.csv", "LEXIS_MODO": "replay"}


def evento(chave):
    return {"Records": [{"eventSource": "aws:sqs", "messageId": "m1", "body": json.dumps(
        {"Records": [{"s3": {"bucket": {"name": "e"}, "object": {"key": chave}}}]})}]}


def test_handler_devolve_a_fila_a_falha_de_provedor_em_vez_de_gravar_falha(golden, monkeypatch):
    from b_tests.conftest import GOLDEN_CSV

    monkeypatch.setattr("lexis.h_interfaces.aws_lambda._CONTEXTO", None)
    s3 = S3Falso()
    s3.put("r", "g.csv", GOLDEN_CSV.read_bytes())
    s3.put("e", "avisos/a.pdf", PDF01)
    ctx = ctx_com(golden, ExtratorQuebrado(ErroExtracao("FALHA_PROVEDOR", "Timeout")))
    r = handler(evento("avisos/a.pdf"), env=ENV, s3=s3, contexto=ctx)
    assert r["batchItemFailures"] == [{"itemIdentifier": "m1"}]
    assert not any(k.startswith("json/") for (_, k) in s3.objetos), "falha transitória não pode virar resultado final"


# --- 3. circuito aberto não sobrescreve resultado bom já existente -------------------------------------------


def test_circuito_aberto_reaproveita_resultado_existente_e_nao_grava_falha(golden, ctx):
    pdfs = {p.name: p.read_bytes() for p in sorted(DOCS.glob("0[1-6]*.pdf"))}
    destino = ArmazenamentoMemoria()
    processar_lote(ArmazenamentoMemoria(pdfs), destino, TrilhaMemoria(), ctx)  # tudo pronto e bom
    antes = {k: destino.ler(k) for k in destino.listar("json/")}

    caido = ExtratorQuebrado(ErroExtracao("FALHA_PROVEDOR", "x"))
    novo = dict(pdfs)
    for i in range(3):  # 3 documentos novos derrubam o provedor e abrem o circuito
        novo[f"00_novo{i}.pdf"] = PDF01 + b"\n%" + str(i).encode()
    ctx_caido = Contexto(golden=golden, modo="live", cfg=Config(), gravacoes=ArmazenamentoMemoria(), usar_ocr=False,
                         cliente_factory=lambda: caido)
    res, _ = processar_lote(ArmazenamentoMemoria(novo), destino, TrilhaMemoria(), ctx_caido)

    por = {n: d for n, _, d in res}
    assert [por[f"00_novo{i}.pdf"] for i in range(3)] == ["PROCESSADO"] * 3  # as 3 que abriram o circuito
    antigos = [n for n in por if not n.startswith("00_novo")]
    assert antigos and all(por[n] == "REUTILIZADO" for n in antigos)  # o que já estava pronto continua valendo
    depois = {k: destino.ler(k) for k in antes}
    assert depois == antes, "resultados bons foram sobrescritos pelo circuito aberto"
    assert not any(json.loads(v)["decisao"]["estado"] == "FALHA_PROCESSAMENTO" for v in depois.values())


# --- 4. tools do modelo contam em custo/orçamento; cache completo não exige chave nem cliente ----------------


def test_documento_todo_em_cache_nao_cria_cliente_nem_exige_chave(golden):
    from b_tests.conftest import REPLAY
    from lexis.g_adapters.local_storage import ArmazenamentoLocal

    criados = []
    ctx = Contexto(golden=golden, modo="auto", cfg=Config(api_key=None), gravacoes=ArmazenamentoLocal(REPLAY),
                   usar_ocr=False, cliente_factory=lambda: criados.append(1))
    r = processar_conteudo("x.pdf", PDF01, ctx, "r")
    assert r.decisao.estado is Decisao.APROVADO_AUTO and criados == []
    assert r.auditoria["chamadas_api"] == 0 and r.auditoria["custo_estimado_usd"] == 0.0


def test_tokens_das_tools_entram_no_custo_e_no_orcamento(golden):
    ext_resp = com_uso(resposta_tool_use(valida()), 100, 50)
    tool_resp = com_uso(SimpleNamespace(content=[]), 40, 10)  # modelo não pediu nenhuma tool; o orquestrador roda
    cliente = ClienteFalso([ext_resp, tool_resp])
    cfg = Config()
    ctx = Contexto(golden=golden, modo="live", cfg=cfg, gravacoes=ArmazenamentoMemoria(), usar_ocr=False,
                   cliente_factory=lambda: ExtratorAnthropic(cfg, cliente=cliente),
                   chamador_factory=chamador_anthropic)
    r = processar_conteudo("a.pdf", PDF01, ctx, "r")
    assert r.auditoria["tokens_entrada"] == 140 and r.auditoria["tokens_saida"] == 60
    assert r.auditoria["chamadas_api"] == 2
    assert r.auditoria["custo_estimado_usd"] == estimar_custo_usd(cfg.modelo, 140, 60)
    assert ctx.vivo().tokens_usados == 200  # as tools também gastam orçamento


# --- 5. custo inclui TODAS as tentativas (reparo de contrato) ------------------------------------------------


def test_custo_soma_a_tentativa_invalida_e_o_reparo(golden):
    invalida = com_uso(SimpleNamespace(content=[SimpleNamespace(type="text", text="oi")]), 100, 30)
    reparo = com_uso(resposta_tool_use(valida()), 120, 40)
    cfg = Config()
    ext = ExtratorAnthropic(cfg, cliente=ClienteFalso([invalida, reparo]))
    _, meta = ext.extrair_texto("t")
    assert (meta.tokens_entrada, meta.tokens_saida, meta.reparos) == (220, 70, 1)
    assert ext.tokens_usados == 290


def test_falha_do_contrato_informa_o_gasto_das_duas_tentativas():
    ruim = com_uso(SimpleNamespace(content=[SimpleNamespace(type="text", text="a")]), 100, 30)
    ext = ExtratorAnthropic(Config(), cliente=ClienteFalso([ruim, ruim]))
    with pytest.raises(ErroExtracao) as e:
        ext.extrair_texto("t")
    assert (e.value.tokens_entrada, e.value.tokens_saida) == (200, 60)


# --- 6. chave de saída sem colisão ---------------------------------------------------------------------------


def test_chaves_de_saida_nao_colidem():
    chaves = {chave_registro(n) for n in ["a/aviso.pdf", "b/aviso.pdf", "aviso.pdf", "aviso.PDF"]}
    assert len(chaves) == 4
    assert chave_registro("01_x.pdf") == "json/01_x.json"  # nome plano continua legível


# --- 7. handler: só PDF e saída ≠ entrada ----------------------------------------------------------------------


def test_handler_ignora_chave_que_nao_e_pdf_e_recusa_saida_igual_a_entrada(golden, monkeypatch, capsys):
    monkeypatch.setattr("lexis.h_interfaces.aws_lambda._CONTEXTO", None)
    ctx = ctx_com(golden, ExtratorFalso(extracao_replay(STEM)))
    s3 = S3Falso()
    s3.put("e", "json/x.json", b"{}")
    r = handler(evento("json/x.json"), env=ENV, s3=s3, contexto=ctx)
    assert r["processados"] == [] and "extensao_nao_pdf" in capsys.readouterr().out
    with pytest.raises(ConfiguracaoInvalida):
        handler(evento("a.pdf"), env={**ENV, "LEXIS_BUCKET_SAIDA": "e"}, s3=s3, contexto=ctx)


def test_construir_contexto_continua_exigindo_configuracao():
    with pytest.raises(ConfiguracaoInvalida):
        construir_contexto({}, S3Falso())


# --- 8. override de preço ilegível não derruba o processamento ---------------------------------------------


def test_preco_ilegivel_vira_custo_desconhecido():
    override = config_do_ambiente({"LEXIS_PRECO_ENTRADA_USD_MTOK": "2,0", "LEXIS_PRECO_SAIDA_USD_MTOK": "10"}).preco_override
    assert estimar_custo_usd("claude-sonnet-5-5", 1000, 1000, override) is None
