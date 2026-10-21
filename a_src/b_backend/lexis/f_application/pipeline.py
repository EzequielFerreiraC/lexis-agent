"""Núcleo por documento: bytes do PDF -> registro estruturado. Sem I/O de arquivo, pronto para Lambda/worker."""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

import lexis
from lexis.a_domain.models import (
    SCHEMA_VERSION,
    Decisao,
    DecisaoSaida,
    Ficha,
    Motivo,
    RegistroSaida,
    TipoAcao,
    ValidacaoGolden,
)
from lexis.a_domain.ports import ArmazenamentoObjetos, ChamadaLLM, ChamadorDeTools, ErroExtracao, Extrator, LeitorOCR
from lexis.a_domain.specs import SPECS
from lexis.b_ingestion.pdf import (
    DocumentoIngerido,
    IngestaoErro,
    ingerir_bytes,
    localizar_bbox,
    renderizar_pagina_png,
    sha256_bytes,
)
from lexis.c_extraction.config import Config
from lexis.c_extraction.costs import FONTE_PRECOS, estimar_custo_usd
from lexis.c_extraction.prompts import sha_prompt
from lexis.c_extraction.recordings import ChamadorComCache, ExtratorComCache
from lexis.d_validation.coherence import resultado_de_regra
from lexis.d_validation.reference_base import Golden
from lexis.f_application.analysis import Entrada, Leitura, analisar, anexar_regra_e_redecidir

CHAVES_DE_IDEMPOTENCIA = ("pipeline", "regras", "prompt_sha", "golden_sha", "schema")


def versoes(golden: Golden, modelo: str, modo: str) -> dict[str, str]:
    return {
        "pipeline": lexis.__version__, "regras": f"{SPECS.versao}+{SPECS.sha[:12]}",
        "prompt_sha": sha_prompt(), "modelo": modelo, "extrator": modo,
        "golden_sha": golden.sha[:12], "schema": SCHEMA_VERSION,
    }


@dataclass
class Contexto:
    """Dependências de uma execução. Tudo externo entra por aqui (portas), nada é global.

    O provedor do modelo e o OCR chegam como fábricas/funções injetadas pelas entradas (CLI, console, Lambda), que
    usam os adaptadores de `g_adapters/` (`anthropic_api`, `tesseract_ocr`). O núcleo não conhece nenhum deles.
    """

    golden: Golden
    modo: str  # replay | auto | live
    cfg: Config
    gravacoes: ArmazenamentoObjetos
    usar_ocr: bool = True
    cliente_factory: Callable[[], Extrator] | None = None  # extrator ao vivo; só é chamada num acerto negativo
    chamador_factory: Callable[[Extrator], ChamadorDeTools | None] | None = None  # function calling ao vivo
    leitor_ocr: LeitorOCR | None = None  # OCR local; sem ele (ou em replay sem gravação), o scan fica sem OCR
    _vivo: Extrator | None = field(default=None, repr=False)

    def vivo(self) -> Extrator | None:
        if self.modo == "replay":
            return None
        if self._vivo is None:
            if self.cliente_factory is None:
                raise ErroExtracao("SEM_EXTRATOR", f"modo {self.modo} exige um provedor de modelo injetado")
            self._vivo = self.cliente_factory()
        return self._vivo

    def fabrica_vivo(self) -> Callable[[], Extrator | None] | None:
        """Fábrica preguiçosa do extrator ao vivo (None em replay): só é chamada num acerto negativo do cache."""
        return None if self.modo == "replay" else self.vivo

    def chamador_vivo(self) -> ChamadorDeTools | None:
        """Function calling ao vivo, sobre o mesmo cliente e orçamento da extração. Sem `chamador_factory` (ou se ela
        não oferecer chamador para este extrator), as tools ficam com o orquestrador."""
        vivo = self.vivo()
        return self.chamador_factory(vivo) if vivo is not None and self.chamador_factory is not None else None

    def reiniciar(self) -> None:
        """Nova execução: zera o orçamento de tokens. O orçamento vale por lote/invocação, nunca por instância."""
        self._vivo = None

    def versoes(self) -> dict[str, str]:
        return versoes(self.golden, self.cfg.modelo if self.modo != "replay" else "replay", self.modo)


def _sem_ocr(_: bytes) -> str | None:
    return None


def _texto_para_modelo(doc: DocumentoIngerido) -> str:
    return "\n\n".join(f"[[página {p.numero}]]\n{p.texto}" for p in doc.paginas)


def registro_falha(
    run_id: str, nome: str, sha: str | None, codigo: str, detalhe: str, vers: dict[str, str],
    auditoria: dict[str, Any] | None = None,
) -> RegistroSaida:
    return RegistroSaida(
        run_id=run_id, documento={"arquivo": nome, "sha256": sha, "fonte": None},
        versoes=vers,
        decisao=DecisaoSaida(
            estado=Decisao.FALHA_PROCESSAMENTO, resumo="O documento não pôde ser processado; nenhum dado foi inferido.",
            motivos=[Motivo(codigo=codigo, mensagem=detalhe)], linha_da_tabela="FALHA: erro antes da análise",
        ),
        evento={"tipo": None}, campos={}, validacao_golden=ValidacaoGolden(status="NAO_AVALIADO"),
        regras=[], auditoria={"erro": {"codigo": codigo, "detalhe": detalhe}, **(auditoria or {})},
        fichas_conferencia=[Ficha(campo=None, codigo=codigo, tipo_acao=TipoAcao.REPROCESSAR,
                                  acao_sugerida="Reprocessar; se persistir, tratar o documento manualmente.",
                                  observado=detalhe)],
    )


def _resumo_chamada(c: ChamadaLLM) -> dict[str, Any]:
    return {k: v for k, v in c.__dict__.items() if v not in (None, 0)}


def _metricas_de_uso(chamadas: list[ChamadaLLM], preco_override: tuple[str, str] | None = None) -> dict[str, Any]:
    """Tokens, tentativas de recuperação e custo estimado (só chamadas reais à API custam)."""
    reais = [c for c in chamadas if c.origem == "API"]
    ent, sai = sum(c.tokens_entrada for c in reais), sum(c.tokens_saida for c in reais)
    custos = [estimar_custo_usd(c.modelo, c.tokens_entrada, c.tokens_saida, preco_override) for c in reais]
    return {
        "chamadas_api": len(reais),
        "chamadas_cache": len(chamadas) - len(reais),
        "tokens_entrada": ent,
        "tokens_saida": sai,
        "reparos_de_contrato": sum(c.reparos for c in reais),
        "custo_estimado_usd": None if any(c is None for c in custos) else round(sum(c or 0.0 for c in custos), 6),
        "custo_fonte": FONTE_PRECOS,
    }


def _agora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def onde_falhou(e: BaseException) -> list[str]:
    """Onde falhou (arquivo:linha:função), SEM a mensagem da exceção, que poderia conter texto do documento."""
    return [f"{PurePosixPath(f.filename).name}:{f.lineno}:{f.name}" for f in traceback.extract_tb(e.__traceback__)[-4:]]


CODIGOS_TRANSITORIOS = {"FALHA_PROVEDOR"}


def processar_conteudo(
    nome: str, conteudo: bytes, ctx: Contexto, run_id: str, *, propagar_transitorios: bool = False,
) -> RegistroSaida:
    """Processa um documento e devolve um registro; falha de documento vira FALHA_PROCESSAMENTO explícito.

    Com `propagar_transitorios=True` (execução orientada a fila), falhas que valem nova tentativa (provedor fora,
    exceção inesperada de infraestrutura) são **levantadas** em vez de gravadas como resultado final, para que a
    fila reentregue e, esgotadas as tentativas, a mensagem vá para a DLQ.
    """
    t0 = time.monotonic()
    inicio = _agora()
    vers = ctx.versoes()
    try:
        doc = ingerir_bytes(nome, conteudo)
    except IngestaoErro as e:
        return registro_falha(run_id, nome, sha256_bytes(conteudo), e.codigo, e.detalhe, vers)

    try:
        ext = ExtratorComCache(ctx.fabrica_vivo(), ctx.gravacoes, doc.sha256, ctx.modo, nome)
        chamadas: list[ChamadaLLM] = []
        if doc.fonte == "NATIVO":
            extr, ch = ext.extrair_texto(_texto_para_modelo(doc))
            chamadas.append(ch)
            entrada = Entrada(
                run_id=run_id, documento=doc.meta(), versoes=vers, golden=ctx.golden,
                principal=Leitura(extr, "TEXTO_NATIVO", [(p.numero, p.texto) for p in doc.paginas]),
                texto_injecao=doc.texto_total, avisos_ingestao=doc.avisos,
                bbox=lambda pg, tr: localizar_bbox(doc, pg, tr),
            )
        elif len(doc.paginas) == 1 and doc.fonte == "SCAN":
            png = renderizar_pagina_png(doc, 1)
            transcricao, ch_t = ext.transcrever(png)
            extr_a, ch_a = ext.extrair_texto(f"[[página 1]]\n{transcricao}", etapa="extracao_transcricao")
            extr_b, ch_b = ext.extrair_imagem(png)
            chamadas += [ch_t, ch_a, ch_b]
            texto_ocr = ext.ler_ocr(png, ctx.leitor_ocr or _sem_ocr) if ctx.usar_ocr else None
            pag = [(1, transcricao)]
            entrada = Entrada(
                run_id=run_id, documento=doc.meta(), versoes=vers, golden=ctx.golden,
                principal=Leitura(extr_a, "TRANSCRICAO_VISAO", pag),
                secundaria=Leitura(extr_b, "LEITURA_DIRETA_VISAO", pag),
                texto_injecao=transcricao + "\n" + (texto_ocr or ""), avisos_ingestao=doc.avisos,
                scan=True, texto_ocr=texto_ocr, ocr_disponivel=texto_ocr is not None,
            )
        else:
            return registro_falha(run_id, nome, doc.sha256, "DOCUMENTO_NAO_SUPORTADO",
                                  "apenas PDF nativo ou scan de 1 página são suportados", vers)

        # Function calling de validação: a conversa com o modelo é gravada como a etapa `validacao_tools`. Em
        # replay ela é reproduzida (as tools que o modelo pediu são reexecutadas pelo código); com gravação
        # válida, nem o modo auto cria cliente ou exige chave.
        chamador = ChamadorComCache(None if ctx.modo == "replay" else ctx.chamador_vivo,
                                    ctx.gravacoes, doc.sha256, ctx.modo, nome)
        entrada.chamador = chamador
        entrada.auditoria = {"modo": ctx.modo, "iniciado_em": inicio}
        reg = analisar(entrada)
        if chamador.ultima is not None and chamador.ultima.chamada is not None:
            chamadas.append(chamador.ultima.chamada)
        # o fallback do provedor responde com um modelo que gravações e mutação não avaliaram: nunca aprova sozinho
        if por_fallback := sorted({c.modelo for c in chamadas if c.aviso}):
            anexar_regra_e_redecidir(reg, resultado_de_regra(
                "MODELO_NAO_AVALIADO", False, [], SPECS.descricao("MODELO_NAO_AVALIADO"),
                esperado=ctx.cfg.modelo, observado=", ".join(por_fallback)))
        modelos = {c.modelo for c in chamadas}
        reg.versoes["modelo"] = ",".join(sorted(modelos)) if modelos else reg.versoes["modelo"]
        reg.auditoria.update({
            "chamadas_llm": [_resumo_chamada(c) for c in chamadas],
            **_metricas_de_uso(chamadas, ctx.cfg.preco_override),
            "concluido_em": _agora(),
            "tempo_total_ms": int((time.monotonic() - t0) * 1000),
        })
        return reg
    except ErroExtracao as e:
        if propagar_transitorios and e.codigo in CODIGOS_TRANSITORIOS:
            raise
        gasto = {"tokens_entrada": e.tokens_entrada, "tokens_saida": e.tokens_saida,
                 "custo_estimado_usd": estimar_custo_usd(ctx.cfg.modelo, e.tokens_entrada, e.tokens_saida,
                                                       ctx.cfg.preco_override)}
        return registro_falha(run_id, nome, doc.sha256, e.codigo, e.detalhe, vers, gasto)
    except Exception as e:  # defesa final: um documento não derruba o lote
        if propagar_transitorios:
            raise
        return registro_falha(run_id, nome, doc.sha256, "ERRO_INESPERADO", type(e).__name__, vers,
                              {"onde": onde_falhou(e)})
