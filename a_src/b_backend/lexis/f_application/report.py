"""Relatório de exceções (curto, para o operador) e resumo da execução."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from lexis.a_domain.models import Decisao, RegistroSaida, Severidade
from lexis.a_domain.ports import ArmazenamentoObjetos
from lexis.e_decision.confidence import ORDEM_NIVEL

_ORDEM = ORDEM_NIVEL


def extracoes_simuladas(registros: list[RegistroSaida]) -> bool:
    return any(
        c.get("origem_fixture") == "SIMULADA_MANUALMENTE"
        for r in registros for c in r.auditoria.get("chamadas_llm", [])
    )


def confianca_minima(r: RegistroSaida) -> str | None:
    niveis = [c.confianca.nivel for c in r.campos.values() if c.estado.value == "EXTRAIDO"]
    return min(niveis, key=lambda n: _ORDEM[n]).value if niveis else None


def _excecao(nome: str, r: RegistroSaida) -> dict[str, object]:
    return {
        "arquivo": nome, "estado": r.decisao.estado.value, "linha_da_tabela": r.decisao.linha_da_tabela,
        "motivos": [m.model_dump() for m in r.decisao.motivos],
        "fichas": [f.model_dump(mode="json") for f in r.fichas_conferencia],
        "para_aprovar": r.decisao.para_aprovar.model_dump(mode="json") if r.decisao.para_aprovar else None,
    }


def resumo_para_aprovar(r: RegistroSaida) -> str:
    """Uma linha: o que basta resolver sozinho ou o que precisa ser resolvido junto."""
    p = r.decisao.para_aprovar
    if p is None or not p.passos:
        return "—"
    basta = [x.codigo for x in p.passos if x.decisao_se_so_este_resolver is Decisao.APROVADO_AUTO]
    if basta:
        return "basta resolver " + " ou ".join(f"`{c}`" for c in dict.fromkeys(basta))
    juntos = "resolver juntos " + " + ".join(f"`{c}`" for c in dict.fromkeys(x.codigo for x in p.passos))
    if p.decisao_com_todos_resolvidos is not Decisao.APROVADO_AUTO:
        juntos += f" (ainda {p.decisao_com_todos_resolvidos.value})"
    return juntos


def gerar_relatorios(resultados: list[tuple[str, RegistroSaida, str]], run_id: str) -> dict[str, str]:
    """Conteúdo dos relatórios por chave de objeto (sem I/O)."""
    regs = [r for _, r, _ in resultados]
    contagem = {d.value: sum(r.decisao.estado is d for r in regs) for d in Decisao}
    pendentes = [(n, r) for n, r, _ in resultados if r.decisao.estado is not Decisao.APROVADO_AUTO]
    aprovados_com_alerta = [
        (n, r) for n, r, _ in resultados
        if r.decisao.estado is Decisao.APROVADO_AUTO
        and (r.documento.get("fonte") == "SCAN"
             or any(x.resultado == "FALHA" and x.severidade is Severidade.AVISO for x in r.regras))
    ]

    linhas = [
        f"# Relatório de exceções — execução `{run_id}`",
        "",
        f"Gerado em {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · catálogo de regras v{regs[0].versoes.get('regras')} "
        f"· extrator: `{regs[0].versoes.get('extrator')}`" if regs else "# Relatório de exceções",
        "",
        f"**{len(regs)} documentos:** " + " · ".join(f"{k} {v}" for k, v in contagem.items() if v),
        "",
    ]
    if extracoes_simuladas(regs):
        linhas += [
            "> ⚠ As extrações desta execução vêm de **gravações simuladas manualmente** (sem chamada real ao modelo). "
            "Valide com `--modo live` e a chave da API antes de confiar em qualquer taxa de acerto.",
            "",
        ]
    linhas += ["## Documentos que exigem atuação", "",
               "| Documento | Estado | Motivos | O que conferir / fazer | Para aprovar |", "|---|---|---|---|---|"]
    for nome, r in pendentes:
        motivos = "; ".join(f"`{m.codigo}`" + (f" ({m.campo})" if m.campo else "") for m in r.decisao.motivos) or "—"
        f = r.fichas_conferencia[0] if r.fichas_conferencia else None
        if f:
            partes = [f.tipo_acao.value]
            if f.esperado:
                partes.append(f"esperado {f.esperado}")
            if f.observado:
                partes.append(f"observado {f.observado}")
            acao = " · ".join(partes)[:230].replace("|", "/")
        else:
            acao = "—"
        linhas.append(f"| {nome} | {r.decisao.estado.value} | {motivos} | {acao} | {resumo_para_aprovar(r)} |")
    if not pendentes:
        linhas.append("| — | — | — | Nenhum documento exige atuação. | — |")
    if aprovados_com_alerta:
        linhas += ["", "## Aprovados automaticamente, com ressalvas que não bloqueiam", ""]
        for nome, r in aprovados_com_alerta:
            ids = sorted({x.id for x in r.regras if x.resultado == "FALHA" and x.severidade is Severidade.AVISO})
            notas = [f"`{i}`" for i in ids]
            if r.documento.get("fonte") == "SCAN":
                ocr_fora = any(x.id == "OCR_INDISPONIVEL" and x.resultado == "FALHA" for x in r.regras)
                notas.append("scan lido por modelo de visão (confiança limitada a MEDIA)"
                             + ("; sem OCR independente — recomenda-se amostragem humana" if ocr_fora else ""))
            linhas.append(f"- {nome}: " + ", ".join(notas))
    linhas += ["", "Detalhe campo a campo, evidência e justificativas: `json/<documento>.json` (seção `fichas_conferencia`).", ""]

    excecoes = json.dumps({
        "run_id": run_id, "contagem": contagem,
        "excecoes": [_excecao(n, r) for n, r in pendentes],
    }, ensure_ascii=False, indent=2) + "\n"

    resumo = json.dumps({
        "run_id": run_id, "contagem": contagem,
        "extracoes_simuladas": extracoes_simuladas(regs),
        "documentos": [{
            "arquivo": n, "disposicao": d, "estado": r.decisao.estado.value,
            "tipo": r.evento.get("tipo"), "confianca_minima_campo_extraido": confianca_minima(r),
            "golden": r.validacao_golden.status,
            "tokens": (r.auditoria.get("tokens_entrada", 0) or 0) + (r.auditoria.get("tokens_saida", 0) or 0),
            "custo_estimado_usd": r.auditoria.get("custo_estimado_usd"),
            "tempo_ms": r.auditoria.get("tempo_total_ms"),
        } for n, r, d in resultados],
        "versoes": regs[0].versoes if regs else {},
    }, ensure_ascii=False, indent=2) + "\n"
    return {
        "relatorio_excecoes.md": "\n".join(linhas),
        "relatorio_excecoes.json": excecoes,
        "resumo_execucao.json": resumo,
    }


def publicar_relatorios(
    destino: ArmazenamentoObjetos, resultados: list[tuple[str, RegistroSaida, str]], run_id: str,
) -> None:
    for chave, conteudo in gerar_relatorios(resultados, run_id).items():
        destino.gravar(chave, conteudo.encode("utf-8"))
