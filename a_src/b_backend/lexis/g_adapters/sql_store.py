"""Projeção das execuções no banco SQL e auditoria amostral dos aprovados automaticamente.

A projeção lê o que já foi gravado (os JSONs da execução e `revisoes.jsonl`) e é idempotente: reimportar a mesma
pasta atualiza os documentos no lugar, sem perder vereditos de auditoria nem revisões já projetadas. Toda consulta é
parametrizada (SQLAlchemy Core); nenhum texto de documento vira SQL.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Engine, and_, create_engine, event, func, insert, inspect, select, text, update
from sqlalchemy.engine import Connection

from lexis.a_domain.models import Decisao, RegistroSaida
from lexis.a_domain.ports import ArmazenamentoObjetos
from lexis.g_adapters.sql_schema import (
    auditoria_amostral,
    campo,
    documento,
    execucao,
    metadata,
    motivo,
    regra_resultado,
    revisao,
    usuario,
)

ORDEM_CONFIANCA = {"BAIXA": 0, "MEDIA": 1, "ALTA": 2}
VEREDITOS = ("CORRETO", "ERRADO")


def url_do_ambiente() -> str | None:
    """`LEXIS_DB_URL` (ex.: mysql+pymysql://lexis:<senha>@mysql:3306/lexis?charset=utf8mb4). Ausente = sem banco."""
    return os.environ.get("LEXIS_DB_URL") or None


def conectar(url: str) -> Engine:
    """Engine com as tabelas criadas. No SQLite, liga as chaves estrangeiras (desligadas por padrão nele)."""
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _fk(conexao: Any, _: Any) -> None:
            conexao.execute("PRAGMA foreign_keys=ON")
    metadata.create_all(engine)
    _alargar_login(engine)
    return engine


def _alargar_login(engine: Engine) -> None:
    """Bancos MySQL criados quando o login tinha 40 caracteres: alarga para caber um e-mail. O SQLite não limita o
    tamanho; outro banco já nasce com 254 (create_all) e não teve a versão antiga."""
    if engine.dialect.name not in ("mysql", "mariadb"):
        return
    coluna = next(c for c in inspect(engine).get_columns("usuario") if c["name"] == "login")
    if (getattr(coluna["type"], "length", None) or 254) < 254:
        with engine.begin() as con:
            con.execute(text("ALTER TABLE usuario MODIFY login VARCHAR(254) NOT NULL COMMENT 'e-mail, em minúsculas'"))


def agora_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # DATETIME sem fuso, sempre em UTC


def _data(valor: str | None) -> date | None:
    try:
        return date.fromisoformat(valor) if valor else None
    except ValueError:
        return None


def _decimal(valor: str | None) -> Decimal | None:
    try:
        return Decimal(valor) if valor else None
    except InvalidOperation:
        return None


def _instante(valor: str | None) -> datetime:
    if not valor:
        return agora_utc()
    d = datetime.fromisoformat(valor)
    return d.astimezone(UTC).replace(tzinfo=None) if d.tzinfo else d


# ----------------------------------------------------------------------- projeção


@dataclass(frozen=True)
class ResultadoImportacao:
    execucao_id: str
    documentos: int
    revisoes: int


def _valor_extraido(reg: RegistroSaida, nome: str) -> str | None:
    c = reg.campos.get(nome)
    return c.valor if c is not None and c.estado.value == "EXTRAIDO" else None


def _linha_documento(execucao_id: str, reg: RegistroSaida, bruto: bytes) -> dict[str, Any]:
    niveis = [c.confianca.nivel.value for c in reg.campos.values() if c.estado.value == "EXTRAIDO"]
    return {
        "execucao_id": execucao_id,
        "arquivo": reg.documento["arquivo"],
        "sha256": reg.documento["sha256"],
        "sha256_registro": hashlib.sha256(bruto).hexdigest(),
        "paginas": reg.documento.get("paginas"),
        "fonte": reg.documento.get("fonte"),
        "decisao": reg.decisao.estado.value,
        "linha_da_tabela": reg.decisao.linha_da_tabela[:80],
        "resumo": reg.decisao.resumo,
        "tipo_evento": reg.evento.get("tipo"),
        "golden_status": reg.validacao_golden.status,
        "emissor": (_valor_extraido(reg, "emissor") or "")[:200] or None,
        "isin": _valor_extraido(reg, "isin"),
        "ticker": _valor_extraido(reg, "ticker"),
        "data_com": _data(_valor_extraido(reg, "data_com")),
        "data_ex": _data(_valor_extraido(reg, "data_ex")),
        "data_pagamento": _data(_valor_extraido(reg, "data_pagamento")),
        "valor_bruto": _decimal(_valor_extraido(reg, "valor_bruto")),
        "moeda": _valor_extraido(reg, "moeda"),
        "confianca_minima": min(niveis, key=ORDEM_CONFIANCA.__getitem__) if niveis else None,
        "registro": reg.model_dump(mode="json"),
    }


def _gravar_filhos(con: Connection, documento_id: int, reg: RegistroSaida) -> None:
    for tabela in (campo, regra_resultado, motivo):
        con.execute(tabela.delete().where(tabela.c.documento_id == documento_id))
    campos = []
    for nome, c in reg.campos.items():
        ev = c.evidencia
        campos.append({
            "documento_id": documento_id, "nome": nome, "estado": c.estado.value,
            "valor": c.valor[:400] if c.valor else None, "natureza": c.natureza, "confianca": c.confianca.nivel.value,
            "justificativa": c.confianca.justificativa, "pagina": ev.pagina if ev else None,
            "trecho": ev.trecho[:400] if ev and ev.trecho else None,
        })
    if campos:
        con.execute(insert(campo), campos)
    regras = [{"documento_id": documento_id, "regra_id": r.id, "severidade": r.severidade.value,
               "resultado": r.resultado, "detalhe": r.detalhe} for r in reg.regras]
    if regras:
        con.execute(insert(regra_resultado), regras)
    motivos = [{"documento_id": documento_id, "ordem": i, "codigo": m.codigo, "campo": m.campo, "mensagem": m.mensagem}
               for i, m in enumerate(reg.decisao.motivos)]
    if motivos:
        con.execute(insert(motivo), motivos)


def _gravar_revisoes(con: Connection, execucao_id: str, revisoes: list[dict[str, Any]]) -> int:
    novas = 0
    for r in revisoes:
        doc_id = con.execute(select(documento.c.id).where(and_(
            documento.c.execucao_id == execucao_id, documento.c.arquivo == r["arquivo"]))).scalar()
        if doc_id is None or con.execute(select(revisao.c.id).where(revisao.c.documento_id == doc_id)).first():
            continue  # documento fora da execução ou revisão já projetada (uma por documento)
        usuario_id = None
        if r.get("usuario"):
            usuario_id = con.execute(select(usuario.c.id).where(usuario.c.login == r["usuario"])).scalar()
        con.execute(insert(revisao).values(
            documento_id=doc_id, decisao=r["decisao"], operador=r["operador"][:80], usuario_id=usuario_id,
            justificativa=r["justificativa"], revisada_em=_instante(r.get("revisada_em")),
            sha256_registro=r["sha256_registro"]))
        novas += 1
    return novas


def projetar_execucao(engine: Engine, execucao_id: str, registros: ArmazenamentoObjetos,
                      revisoes: list[dict[str, Any]] | None = None) -> ResultadoImportacao:
    """Projeta os registros `json/*.json` de uma execução (e suas revisões) numa transação só."""
    brutos = [(k, b) for k in sorted(registros.listar("json/")) if k.endswith(".json") and (b := registros.ler(k))]
    regs = [(RegistroSaida.model_validate_json(b), b) for _, b in brutos]
    if not regs:
        raise ValueError(f"nenhum registro em json/ para a execução {execucao_id}")
    v = regs[0][0].versoes
    cab = {"run_id": regs[0][0].run_id, "importada_em": agora_utc(), "modo": regs[0][0].auditoria.get("modo"),
           "versao_pipeline": v.get("pipeline"), "versao_regras": v.get("regras"), "prompt_sha": v.get("prompt_sha"),
           "modelo": v.get("modelo"), "golden_sha": v.get("golden_sha"), "schema_version": v.get("schema"),
           "total_documentos": len(regs)}
    with engine.begin() as con:
        if con.execute(select(execucao.c.id).where(execucao.c.id == execucao_id)).first():
            con.execute(update(execucao).where(execucao.c.id == execucao_id).values(**cab))
        else:
            con.execute(insert(execucao).values(id=execucao_id, **cab))
        for reg, bruto in regs:
            linha = _linha_documento(execucao_id, reg, bruto)
            existente = con.execute(select(documento.c.id).where(and_(
                documento.c.execucao_id == execucao_id, documento.c.arquivo == linha["arquivo"]))).scalar()
            if existente is None:
                pk = con.execute(insert(documento).values(**linha)).inserted_primary_key
                assert pk is not None
                doc_id = int(pk[0])
            else:
                doc_id = int(existente)
                con.execute(update(documento).where(documento.c.id == doc_id).values(**linha))
            _gravar_filhos(con, doc_id, reg)
        novas = _gravar_revisoes(con, execucao_id, revisoes or [])
    return ResultadoImportacao(execucao_id, len(regs), novas)


def ler_revisoes(conteudo: bytes | None) -> list[dict[str, Any]]:
    return [json.loads(linha) for linha in (conteudo or b"").decode("utf-8").splitlines() if linha.strip()]


# ----------------------------------------------------------------------- auditoria amostral


def _estrato(tipo: str | None, fonte: str | None) -> str:
    return f"{tipo or 'DESCONHECIDO'}/{fonte or 'NATIVO'}"


def sortear_auditoria(engine: Engine, taxa: float, semente: str, minimo_por_estrato: int = 1) -> list[int]:
    """Sorteia, entre os APROVADO_AUTO ainda não sorteados, `taxa` de cada estrato (tipo de evento × fonte).

    A revisão humana nunca revela um falso aprovado automático (ali o sistema já tinha dúvida): só uma amostra
    aleatória dos aprovados mede esse erro. Estratificar garante que tipos raros (bonificação, scan) entrem.
    O sorteio é reproduzível: mesma semente e mesmo conjunto de candidatos dão a mesma amostra."""
    if not 0 < taxa <= 1:
        raise ValueError("a taxa deve estar em (0, 1]")
    with engine.begin() as con:
        ja = select(auditoria_amostral.c.documento_id)
        candidatos = con.execute(
            select(documento.c.id, documento.c.tipo_evento, documento.c.fonte, documento.c.sha256)
            .where(documento.c.decisao == Decisao.APROVADO_AUTO.value, documento.c.id.not_in(ja))
            .order_by(documento.c.sha256, documento.c.id)).all()
        por_estrato: dict[str, list[int]] = defaultdict(list)
        for doc_id, tipo, fonte, _ in candidatos:
            por_estrato[_estrato(tipo, fonte)].append(int(doc_id))
        sorteados: list[int] = []
        instante = agora_utc()
        for estrato, ids in sorted(por_estrato.items()):
            n = min(len(ids), max(minimo_por_estrato, math.ceil(taxa * len(ids))))
            escolhidos = sorted(random.Random(f"{semente}:{estrato}").sample(ids, n))  # noqa: S311 - amostragem, não segredo
            con.execute(insert(auditoria_amostral), [
                {"documento_id": d, "estrato": estrato, "sorteada_em": instante, "semente": semente} for d in escolhidos])
            sorteados += escolhidos
    return sorteados


def pendentes(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as con:
        q = (select(auditoria_amostral.c.id, auditoria_amostral.c.estrato, documento.c.execucao_id,
                    documento.c.arquivo, documento.c.emissor, documento.c.data_pagamento)
             .join(documento, documento.c.id == auditoria_amostral.c.documento_id)
             .where(auditoria_amostral.c.veredito.is_(None))
             .order_by(documento.c.data_pagamento, auditoria_amostral.c.id))
        return [dict(r._mapping) for r in con.execute(q)]


def registrar_veredito(engine: Engine, auditoria_id: int, veredito: str, auditor: str, *,
                       campo_errado: str | None = None, valor_correto: str | None = None,
                       observacao: str | None = None) -> None:
    """Veredito de quem conferiu o documento contra o aviso, às cegas. ERRADO exige o campo e o valor certo:
    é esse rótulo por campo que permite calibrar a confiança."""
    if veredito not in VEREDITOS:
        raise ValueError(f"veredito deve ser {' ou '.join(VEREDITOS)}")
    if len(auditor.strip()) < 2:
        raise ValueError("informe quem auditou")
    if veredito == "ERRADO" and not (campo_errado and valor_correto is not None):
        raise ValueError("veredito ERRADO exige o campo errado e o valor correto")
    with engine.begin() as con:
        alterados = con.execute(
            update(auditoria_amostral)
            .where(auditoria_amostral.c.id == auditoria_id, auditoria_amostral.c.veredito.is_(None))
            .values(veredito=veredito, auditor=auditor.strip()[:80], campo_errado=campo_errado,
                    valor_correto=valor_correto, observacao=observacao, registrada_em=agora_utc())).rowcount
    if alterados != 1:
        raise ValueError("auditoria inexistente ou já registrada (o veredito não se reescreve)")


def wilson(erros: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Intervalo de Wilson (95%) para uma proporção: não colapsa em 0 com amostra pequena, ao contrário do normal."""
    if n == 0:
        return None
    p = erros / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    margem = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(max(0.0, centro - margem), 4), round(min(1.0, centro + margem), 4)


def metricas(engine: Engine) -> dict[str, Any]:
    """Métricas operacionais que valem para qualquer lote: abstenção e falso aprovado automático estimado."""
    with engine.connect() as con:
        por_decisao = {d: int(n) for d, n in con.execute(
            select(documento.c.decisao, func.count()).group_by(documento.c.decisao))}
        linhas = con.execute(
            select(auditoria_amostral.c.estrato, auditoria_amostral.c.veredito, func.count())
            .group_by(auditoria_amostral.c.estrato, auditoria_amostral.c.veredito)).all()
    total = sum(por_decisao.values())
    estratos: dict[str, dict[str, Any]] = defaultdict(lambda: {"sorteados": 0, "auditados": 0, "erros": 0})
    for estrato, veredito, n in linhas:
        e = estratos[estrato]
        e["sorteados"] += n
        if veredito is not None:
            e["auditados"] += n
            e["erros"] += n if veredito == "ERRADO" else 0
    for e in estratos.values():
        e["taxa_erro"] = round(e["erros"] / e["auditados"], 4) if e["auditados"] else None
        e["ic95"] = wilson(e["erros"], e["auditados"])
    auditados = sum(e["auditados"] for e in estratos.values())
    erros = sum(e["erros"] for e in estratos.values())
    return {
        "documentos": total,
        "por_decisao": por_decisao,
        "taxa_abstencao": round(1 - por_decisao.get(Decisao.APROVADO_AUTO.value, 0) / total, 4) if total else None,
        "auditoria_amostral": {
            "auditados": auditados, "erros": erros,
            "taxa_falso_auto_aprovado": round(erros / auditados, 4) if auditados else None,
            "ic95": wilson(erros, auditados),
            "por_estrato": dict(sorted(estratos.items())),
        },
        "aviso": "A taxa de falso aprovado automático só existe com vereditos registrados; o intervalo de confiança "
                 "diz quanto ela ainda pode estar errada com a amostra atual.",
    }
