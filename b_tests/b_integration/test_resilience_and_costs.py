"""Circuit breaker do lote, custo estimado e métricas de roteamento."""

from b_tests.conftest import DOCS, ExtratorFalso, extracao_replay
from lexis.a_domain.ports import ChamadaLLM, ErroExtracao
from lexis.c_extraction.config import Config
from lexis.c_extraction.costs import estimar_custo_usd
from lexis.f_application.batch import processar_lote
from lexis.f_application.pipeline import Contexto
from lexis.g_adapters.ambiente import config_do_ambiente
from lexis.g_adapters.local_execution import processar_documento
from lexis.g_adapters.local_storage import ArmazenamentoMemoria
from lexis.g_adapters.local_trail import TrilhaMemoria


class ExtratorCaido(ExtratorFalso):
    def __init__(self, codigo: str) -> None:
        super().__init__(extracao_replay("01_energetica_vale_tiete_dividendo"))
        self.codigo, self.chamadas = codigo, 0

    def extrair_texto(self, texto, etapa="extracao"):
        self.chamadas += 1
        raise ErroExtracao(self.codigo, "simulado")


def _lote(golden, falso, n=6):
    pdfs = sorted(DOCS.glob("0[1-6]*.pdf"))[:n]
    entrada = ArmazenamentoMemoria({p.name: p.read_bytes() for p in pdfs})
    ctx = Contexto(golden=golden, modo="live", cfg=Config(), gravacoes=ArmazenamentoMemoria(), usar_ocr=False,
                   cliente_factory=lambda: falso)
    trilha = TrilhaMemoria()
    res, _ = processar_lote(entrada, ArmazenamentoMemoria(), trilha, ctx)
    return res, trilha


def test_circuito_abre_apos_tres_falhas_do_provedor_e_poupa_as_chamadas(golden):
    falso = ExtratorCaido("FALHA_PROVEDOR")
    res, trilha = _lote(golden, falso)
    codigos = [r.decisao.motivos[0].codigo for _, r, _ in res]
    assert codigos == ["FALHA_PROVEDOR"] * 3 + ["CIRCUITO_ABERTO"] * 3
    assert falso.chamadas == 3  # as 3 últimas não chamaram o provedor
    assert [d for _, _, d in res][3:] == ["NAO_PROCESSADO"] * 3
    assert any(e["evento"] == "circuito_aberto" for e in trilha.eventos)


def test_orcamento_excedido_aborta_o_lote_imediatamente(golden):
    falso = ExtratorCaido("ORCAMENTO_EXCEDIDO")
    res, _ = _lote(golden, falso)
    assert falso.chamadas == 1
    assert [r.decisao.motivos[0].codigo for _, r, _ in res][1:] == ["CIRCUITO_ABERTO"] * 5


def test_falha_isolada_nao_abre_o_circuito(golden):
    class Intermitente(ExtratorCaido):
        def extrair_texto(self, texto, etapa="extracao"):
            self.chamadas += 1
            if self.chamadas % 2:
                raise ErroExtracao("FALHA_PROVEDOR", "simulado")
            return self.extracao, ChamadaLLM(etapa, "m", "API")

    falso = Intermitente("x")
    res, _ = _lote(golden, falso)
    assert falso.chamadas == len(res) and all(d != "NAO_PROCESSADO" for _, _, d in res)  # sucesso zera a contagem


def test_custo_estimado_conhecido_e_desconhecido():
    assert config_do_ambiente({}).preco_override is None
    assert estimar_custo_usd("claude-sonnet-5-5", 1_000_000, 1_000_000) == 12.0  # 2 + 10 USD/MTok
    assert estimar_custo_usd("modelo-sem-preco", 10, 10) is None  # nunca inventa preço
    # contrato próprio (lido do ambiente pelo adaptador) sobrescreve; com um preço só, não vale
    override = config_do_ambiente({"LEXIS_PRECO_ENTRADA_USD_MTOK": "1", "LEXIS_PRECO_SAIDA_USD_MTOK": "3"}).preco_override
    assert estimar_custo_usd("modelo-sem-preco", 1_000_000, 1_000_000, override) == 4.0
    assert config_do_ambiente({"LEXIS_PRECO_ENTRADA_USD_MTOK": "1"}).preco_override is None


def test_registro_traz_timestamps_tokens_e_custo(golden):
    class Vivo(ExtratorFalso):
        def extrair_texto(self, texto, etapa="extracao"):
            return self.extracao, ChamadaLLM(etapa, "claude-sonnet-5-5", "API", 1000, 500)

    falso = Vivo(extracao_replay("01_energetica_vale_tiete_dividendo"))
    entrada = ArmazenamentoMemoria({"01.pdf": (DOCS / "01_energetica_vale_tiete_dividendo.pdf").read_bytes()})
    ctx = Contexto(golden=golden, modo="live", cfg=Config(), gravacoes=ArmazenamentoMemoria(), usar_ocr=False,
                   cliente_factory=lambda: falso)
    res, _ = processar_lote(entrada, ArmazenamentoMemoria(), TrilhaMemoria(), ctx)
    aud = res[0][1].auditoria
    assert aud["iniciado_em"] <= aud["concluido_em"] and aud["tokens_entrada"] == 1000 and aud["tokens_saida"] == 500
    assert aud["custo_estimado_usd"] == 0.007 and "estimativa" in aud["custo_fonte"]  # 1000×2/1e6 + 500×10/1e6


def test_replay_nao_tem_custo_nem_chamada_api(ctx):
    aud = processar_documento(DOCS / "02_banco_meridional_jcp.pdf", ctx, "t").auditoria
    # 2 gravações reaproveitadas: a extração e a conversa de function calling (validacao_tools)
    assert aud["chamadas_api"] == 0 and aud["chamadas_cache"] == 2 and aud["custo_estimado_usd"] == 0.0
