"""Orquestração de lote sobre as portas: idempotência por SHA-256, deduplicação, auditoria e isolamento de falhas."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from lexis.a_domain.models import Decisao, RegistroSaida, RegraResultado, Severidade
from lexis.a_domain.ports import ArmazenamentoObjetos, TrilhaAuditoria
from lexis.a_domain.specs import SPECS
from lexis.b_ingestion.pdf import sha256_bytes
from lexis.f_application.analysis import anexar_regra_e_redecidir
from lexis.f_application.pipeline import CHAVES_DE_IDEMPOTENCIA, Contexto, processar_conteudo, registro_falha

Resultado = tuple[str, RegistroSaida, str]  # (nome, registro, disposição)

FALHAS_CONSECUTIVAS_PARA_ABRIR_CIRCUITO = 3
CODIGOS_DE_PROVEDOR = {"FALHA_PROVEDOR"}
# credencial recusada falharia igual em todos os documentos: parar evita N chamadas inúteis
CODIGOS_QUE_ABORTAM_O_LOTE = {"ORCAMENTO_EXCEDIDO", "CREDENCIAL_RECUSADA"}


def _codigo_de_falha(reg: RegistroSaida) -> str | None:
    if reg.decisao.estado is not Decisao.FALHA_PROCESSAMENTO or not reg.decisao.motivos:
        return None
    return reg.decisao.motivos[0].codigo


def chave_registro(nome: str) -> str:
    """`json/<caminho sem .pdf>.json`. Mantém o diretório (a/x.pdf != b/x.pdf) e a extensão quando não é `.pdf`
    minúsculo (x.PDF != x.pdf), evitando que arquivos distintos sobrescrevam o mesmo resultado."""
    p = PurePosixPath(nome)
    base = p.with_suffix("") if p.suffix == ".pdf" else p
    return f"json/{base}.json"


def serializar_registro(reg: RegistroSaida) -> bytes:
    return (json.dumps(reg.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


# Para onde o log vai é decisão de quem roda o núcleo (`g_adapters/log_trail.configurar_log`); sem handler, nada sai.
LOG = logging.getLogger("lexis.lote")


def _log(evento: str, **dados: Any) -> None:
    """Log estruturado: apenas ids, hashes, códigos e contagens. Nunca texto do documento."""
    LOG.info(json.dumps({"ts": datetime.now(UTC).isoformat(timespec="seconds"), "evento": evento, **dados},
                        ensure_ascii=False))


def reutilizavel(destino: ArmazenamentoObjetos, nome: str, sha: str, vers: dict[str, str]) -> RegistroSaida | None:
    """Registro já gerado para o MESMO conteúdo e as MESMAS versões. Falhas nunca são reaproveitadas."""
    bruto = destino.ler(chave_registro(nome))
    if bruto is None:
        return None
    try:
        antigo = RegistroSaida.model_validate_json(bruto)
    except Exception:
        return None
    if antigo.decisao.estado is Decisao.FALHA_PROCESSAMENTO or antigo.documento.get("sha256") != sha:
        return None
    if any(antigo.versoes.get(k) != vers.get(k) for k in CHAVES_DE_IDEMPOTENCIA):
        return None
    return antigo


def processar_documento_idempotente(
    nome: str, conteudo: bytes, destino: ArmazenamentoObjetos, ctx: Contexto, run_id: str, forcar: bool = False,
    *, propagar_transitorios: bool = False,
) -> tuple[RegistroSaida, str]:
    """Unidade que uma Lambda/worker executa por mensagem: reaproveita ou processa, e grava o registro."""
    sha = sha256_bytes(conteudo)
    if not forcar and (reg := reutilizavel(destino, nome, sha, ctx.versoes())) is not None:
        return reg, "REUTILIZADO"
    reg = processar_conteudo(nome, conteudo, ctx, run_id, propagar_transitorios=propagar_transitorios)
    destino.gravar(chave_registro(nome), serializar_registro(reg))
    return reg, "PROCESSADO"


def processar_lote(
    fonte: ArmazenamentoObjetos, destino: ArmazenamentoObjetos, trilha: TrilhaAuditoria, ctx: Contexto,
    *, forcar: bool = False, ao_concluir: Callable[[int, int, Resultado], None] | None = None,
) -> tuple[list[Resultado], str]:
    """Processa todos os PDFs de `fonte`. Retorna [(nome, registro, disposição)] e o run_id.

    `ao_concluir(indice, total, resultado)` é chamado após cada documento (progresso para uma interface)."""
    run_id = uuid.uuid4().hex[:12]
    ctx.reiniciar()  # orçamento de tokens vale por lote
    vers = ctx.versoes()

    def evento(tipo: str, **d: Any) -> None:
        trilha.registrar({"ts": datetime.now(UTC).isoformat(timespec="seconds"), "run_id": run_id, "evento": tipo, **d})

    nomes = [k for k in fonte.listar() if k.lower().endswith(".pdf")]
    evento("run_inicio", versoes=vers, documentos=len(nomes), modo=ctx.modo)
    _log("run_inicio", run_id=run_id, documentos=len(nomes), modo=ctx.modo)
    resultados: list[Resultado] = []

    def registrar(res: Resultado) -> None:
        resultados.append(res)
        if ao_concluir is not None:
            ao_concluir(len(resultados), len(nomes), res)

    vistos: dict[str, str] = {}
    consecutivas = 0
    circuito_aberto: str | None = None  # código que abriu o circuito
    for nome in nomes:
        conteudo = fonte.ler(nome)
        if conteudo is None:
            continue
        sha = sha256_bytes(conteudo)
        if sha in vistos:
            evento("doc_duplicado_no_lote", arquivo=nome, sha256=sha, igual_a=vistos[sha])
            original = next(r for n, r, _ in resultados if n == vistos[sha])
            registrar((nome, original, "DUPLICADO_NO_LOTE"))
            continue
        vistos[sha] = nome
        if circuito_aberto is not None:
            # Circuito aberto: não chama o provedor, mas o que já está pronto (mesmo conteúdo e versões) continua
            # valendo; e nada é gravado em `json/`, para nunca sobrescrever um resultado bom com uma falha.
            antigo = None if forcar else reutilizavel(destino, nome, sha, vers)
            if antigo is not None:
                registrar((nome, antigo, "REUTILIZADO"))
                continue
            reg = registro_falha(
                run_id, nome, sha, "CIRCUITO_ABERTO",
                f"lote interrompido após {circuito_aberto}; documento não processado (nenhuma chamada feita)", vers,
            )
            registrar((nome, reg, "NAO_PROCESSADO"))
            evento("doc_nao_processado", arquivo=nome, sha256=sha, motivo=circuito_aberto)
            continue
        reg, disposicao = processar_documento_idempotente(nome, conteudo, destino, ctx, run_id, forcar)
        registrar((nome, reg, disposicao))
        codigo = _codigo_de_falha(reg)
        consecutivas = consecutivas + 1 if codigo in CODIGOS_DE_PROVEDOR else 0
        if codigo in CODIGOS_QUE_ABORTAM_O_LOTE or consecutivas >= FALHAS_CONSECUTIVAS_PARA_ABRIR_CIRCUITO:
            circuito_aberto = codigo
            evento("circuito_aberto", codigo=codigo, falhas_consecutivas=consecutivas)
        falhas = [r.id for r in reg.regras if r.resultado == "FALHA" and r.severidade is not Severidade.INFO]
        evento("doc_concluido", arquivo=nome, sha256=reg.documento.get("sha256"), disposicao=disposicao,
               decisao=reg.decisao.estado.value, regras_com_falha=falhas,
               tools=[c.get("tool") for c in reg.auditoria.get("chamadas_de_tools", []) if c.get("aceita")],
               tempo_ms=reg.auditoria.get("tempo_total_ms"))
        _log("doc_concluido", run_id=run_id, arquivo=nome, disposicao=disposicao, decisao=reg.decisao.estado.value)

    alterados = _anexar_duplicatas_de_evento(resultados)
    for nome, reg, disp in resultados:
        if disp == "PROCESSADO" or (nome in alterados and disp == "REUTILIZADO"):
            destino.gravar(chave_registro(nome), serializar_registro(reg))
    # Selo dos registros como ficaram gravados (depois das duplicatas de evento): `lexis auditar` confere a pasta
    # contra estes hashes, e a cadeia da trilha protege a própria lista.
    publicados: dict[str, str] = {}
    for nome, _, _ in resultados:
        bruto = destino.ler(chave_registro(nome))
        if bruto is not None:
            publicados[chave_registro(nome)] = sha256_bytes(bruto)
    evento("registros_publicados", registros=publicados)
    evento("run_fim", por_decisao={d.value: sum(r.decisao.estado is d for _, r, _ in resultados) for d in Decisao})
    return resultados, run_id


def _anexar_duplicatas_de_evento(resultados: list[Resultado]) -> set[str]:
    """Mesmo ISIN + tipo + data com em arquivos diferentes: os dois vão à revisão (ERRO), para o mesmo evento nunca
    sair aprovado duas vezes (lançamento em dobro no processo seguinte). Devolve os documentos alterados."""
    alterados: set[str] = set()
    por_chave: dict[tuple[str, str, str], list[str]] = {}
    for nome, r, disp in resultados:
        if disp == "DUPLICADO_NO_LOTE":
            continue
        isin, com = r.campos.get("isin"), r.campos.get("data_com")
        if isin and com and isin.valor and com.valor and r.evento.get("tipo"):
            por_chave.setdefault((isin.valor, str(r.evento["tipo"]), com.valor), []).append(nome)
    for nomes in por_chave.values():
        if len(nomes) < 2:
            continue
        for nome, r, _ in resultados:
            if nome in nomes and not any(x.id == "DUPLICATA_POSSIVEL" for x in r.regras):
                outros = ", ".join(n for n in nomes if n != nome)
                anexar_regra_e_redecidir(r, RegraResultado(
                    id="DUPLICATA_POSSIVEL", severidade=Severidade(SPECS.severidade("DUPLICATA_POSSIVEL")),
                    resultado="FALHA", campos=["isin", "data_com"],
                    detalhe=SPECS.descricao("DUPLICATA_POSSIVEL"), observado=f"também em: {outros}"))
                alterados.add(nome)
    return alterados
