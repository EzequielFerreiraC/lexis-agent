"""Tabela de decisão: a primeira linha verdadeira define o estado do registro. Cada linha tem teste próprio."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from lexis.a_domain.models import (
    CampoSaida,
    Decisao,
    DecisaoSaida,
    EstadoCampo,
    Motivo,
    Nivel,
    ParaAprovar,
    PassoParaAprovar,
    RegraResultado,
    Severidade,
)
from lexis.a_domain.specs import SPECS
from lexis.e_decision.confidence import ORDEM_NIVEL


@dataclass
class Contexto:
    tipo: str
    campos: dict[str, CampoSaida]
    regras: list[RegraResultado]
    criticos: list[str]
    obrigatorios_pendentes: list[str]

    def falhas(self, sev: Severidade | None = None) -> list[RegraResultado]:
        return [r for r in self.regras if r.resultado == "FALHA" and (sev is None or r.severidade is sev)]


@dataclass(frozen=True)
class Linha:
    id: str
    descricao: str
    condicao: Callable[[Contexto], bool]
    estado: Decisao


def _seguranca(c: Contexto) -> bool:
    ids = set(SPECS.politica["revisao_por_sinais_de_seguranca"])
    return any(r.id in ids for r in c.falhas())


def _erro_regra(c: Contexto) -> bool:
    return bool(c.falhas(Severidade.ERRO))


def _titulo(c: Contexto) -> bool:
    return bool(SPECS.politica["revisao_por_titulo_diverge_corpo"]) and any(
        r.id == "TITULO_DIVERGE_CORPO" for r in c.falhas()
    )


def _campo_critico_fraco(c: Contexto) -> bool:
    minimo = Nivel(SPECS.politica["confianca_minima_campo_critico"])
    for nome in c.criticos:
        campo = c.campos.get(nome)
        if campo is None:
            continue
        if campo.estado in (EstadoCampo.AUSENTE, EstadoCampo.INCERTO):
            return True
        if campo.estado is EstadoCampo.EXTRAIDO and ORDEM_NIVEL[campo.confianca.nivel] < ORDEM_NIVEL[minimo]:
            return True
    return False


def _scan_sem_ocr(c: Contexto) -> bool:
    return bool(SPECS.politica["revisao_scan_sem_ocr_independente"]) and any(
        r.id == "OCR_INDISPONIVEL" for r in c.falhas()
    )


TABELA: tuple[Linha, ...] = (
    Linha("L1", "Sinal de segurança (injeção, texto oculto, conteúdo ativo)", _seguranca, Decisao.REVISAO_HUMANA),
    Linha("L2", "Alguma regra de severidade ERRO falhou (inclui golden, datas, valores, evidência)", _erro_regra, Decisao.REVISAO_HUMANA),
    Linha("L3", "Título diverge do corpo (política: revisão por risco tributário)", _titulo, Decisao.REVISAO_HUMANA),
    Linha("L4", "Campo crítico ausente, incerto ou abaixo da confiança mínima", _campo_critico_fraco, Decisao.REVISAO_HUMANA),
    Linha("L5", "Scan sem leitor independente do modelo (política: revisão por erros correlacionados)", _scan_sem_ocr, Decisao.REVISAO_HUMANA),
    Linha("L6", "Informação obrigatória pendente de aviso complementar", lambda c: bool(c.obrigatorios_pendentes), Decisao.AGUARDA_EMISSOR),
    Linha("L7", "Nenhuma das anteriores", lambda c: True, Decisao.APROVADO_AUTO),
)


def _linha(c: Contexto) -> Linha:
    return next(linha for linha in TABELA if linha.condicao(c))


# ------------------------------------------------------------------ o que falta para aprovar
@dataclass(frozen=True)
class _Bloqueio:
    codigo: str
    campo: str | None
    linha: str
    condicao: str
    resolver: Callable[[Contexto], Contexto]


def _rebaixado_so_por_regra(c: Contexto, nome: str) -> bool:
    """Campo extraído em BAIXA porque alguma regra ERRO reprovada aponta para ele (é o que `confidence.py` faz)."""
    campo = c.campos.get(nome)
    return (campo is not None and campo.estado is EstadoCampo.EXTRAIDO and campo.confianca.nivel is Nivel.BAIXA
            and any(nome in r.campos for r in c.falhas(Severidade.ERRO)))


def _regra_resolvida(indice: int) -> Callable[[Contexto], Contexto]:
    """A regra passa e, como em `confidence.py`, os campos dela que só estavam em BAIXA por regra reprovada voltam ao
    mínimo aceitável (se outra regra ERRO ainda os reprova, continuam em BAIXA)."""

    def resolver(c: Contexto) -> Contexto:
        regras = list(c.regras)
        regra = regras[indice]
        regras[indice] = regra.model_copy(update={"resultado": "OK"})
        depois = replace(c, regras=regras)
        minimo = Nivel(SPECS.politica["confianca_minima_campo_critico"])
        for nome in regra.campos:
            if _rebaixado_so_por_regra(c, nome) and not any(nome in r.campos for r in depois.falhas(Severidade.ERRO)):
                depois = _campo_resolvido(nome, minimo)(depois)
        return depois

    return resolver


def _campo_resolvido(nome: str, minimo: Nivel) -> Callable[[Contexto], Contexto]:
    def resolver(c: Contexto) -> Contexto:
        campo = c.campos[nome]
        novo = campo.model_copy(update={"estado": EstadoCampo.EXTRAIDO,
                                        "confianca": campo.confianca.model_copy(update={"nivel": minimo})})
        return replace(c, campos={**c.campos, nome: novo})

    return resolver


def _pendente_resolvido(nome: str) -> Callable[[Contexto], Contexto]:
    return lambda c: replace(c, obrigatorios_pendentes=[n for n in c.obrigatorios_pendentes if n != nome])


def _bloqueios(c: Contexto) -> list[_Bloqueio]:
    """Tudo que torna verdadeira alguma linha antes da L7, na ordem da tabela."""
    seguranca = set(SPECS.politica["revisao_por_sinais_de_seguranca"])
    saida: list[_Bloqueio] = []
    for i, r in enumerate(c.regras):
        if r.resultado != "FALHA":
            continue
        campo = r.campos[0] if r.campos else None
        if r.id in seguranca:
            saida.append(_Bloqueio(r.id, campo, "L1", "sinal de segurança descartado após verificação", _regra_resolvida(i)))
        elif r.severidade is Severidade.ERRO:
            saida.append(_Bloqueio(r.id, campo, "L2", "a regra passar", _regra_resolvida(i)))
        elif r.id == "TITULO_DIVERGE_CORPO" and SPECS.politica["revisao_por_titulo_diverge_corpo"]:
            saida.append(_Bloqueio(r.id, campo, "L3", "título e corpo indicarem o mesmo tipo de evento", _regra_resolvida(i)))
        elif r.id == "OCR_INDISPONIVEL" and SPECS.politica["revisao_scan_sem_ocr_independente"]:
            saida.append(_Bloqueio(r.id, None, "L5", "um leitor independente do modelo (OCR) corroborar os valores",
                                   _regra_resolvida(i)))
    minimo = Nivel(SPECS.politica["confianca_minima_campo_critico"])
    for nome in c.criticos:
        # rebaixado por regra reprovada é consequência dela: resolver a regra já restaura o campo
        if nome in c.campos and _campo_critico_fraco(replace(c, criticos=[nome])) and not _rebaixado_so_por_regra(c, nome):
            saida.append(_Bloqueio("CAMPO_CRITICO_FRACO", nome, "L4", f"valor extraído com confiança ≥ {minimo.value}",
                                   _campo_resolvido(nome, minimo)))
    for nome in c.obrigatorios_pendentes:
        saida.append(_Bloqueio("CAMPO_PENDENTE_NO_AVISO", nome, "L6", "o emissor informar o valor (aviso complementar)",
                               _pendente_resolvido(nome)))
    return sorted(saida, key=lambda b: b.linha)


def para_aprovar(c: Contexto) -> ParaAprovar:
    """Reavalia a tabela com cada bloqueio resolvido sozinho e com todos juntos. Determinístico, sem o modelo."""
    bloqueios = _bloqueios(c)
    passos = []
    for b in bloqueios:
        linha = _linha(b.resolver(c))
        passos.append(PassoParaAprovar(codigo=b.codigo, campo=b.campo, linha_que_aciona=b.linha, condicao=b.condicao,
                                       decisao_se_so_este_resolver=linha.estado, linha_se_so_este_resolver=linha.id))
    todos = c
    for b in bloqueios:
        todos = b.resolver(todos)
    final = _linha(todos)
    return ParaAprovar(passos=passos, decisao_com_todos_resolvidos=final.estado, linha_com_todos_resolvidos=final.id)


def decidir(c: Contexto) -> DecisaoSaida:
    """Primeira linha verdadeira define o estado; motivos reúnem tudo que o operador precisa saber."""
    escolhida = _linha(c)
    motivos: list[Motivo] = []
    for r in c.falhas(Severidade.ERRO):
        motivos.append(Motivo(codigo=r.id, mensagem=r.detalhe, campo=r.campos[0] if r.campos else None))
    for r in c.falhas(Severidade.AVISO):
        if r.id in SPECS.politica["revisao_por_sinais_de_seguranca"] or (
            r.id == "TITULO_DIVERGE_CORPO" and SPECS.politica["revisao_por_titulo_diverge_corpo"]
        ):
            motivos.append(Motivo(codigo=r.id, mensagem=r.detalhe, campo=r.campos[0] if r.campos else None))
    if _scan_sem_ocr(c):
        motivos.append(Motivo(codigo="OCR_INDISPONIVEL", mensagem=SPECS.descricao("OCR_INDISPONIVEL"), campo=None))
    for nome in c.criticos:
        campo = c.campos.get(nome)
        coberto = any(nome in r.campos for r in c.falhas(Severidade.ERRO))
        if campo and campo.estado is EstadoCampo.EXTRAIDO and campo.confianca.nivel is Nivel.BAIXA and not coberto:
            motivos.append(Motivo(codigo="CAMPO_CRITICO_BAIXA_CONFIANCA", mensagem="Campo crítico com confiança BAIXA.", campo=nome))
    for nome in c.obrigatorios_pendentes:
        motivos.append(Motivo(codigo="CAMPO_PENDENTE_NO_AVISO", mensagem=SPECS.descricao("CAMPO_PENDENTE_NO_AVISO"), campo=nome))

    resumo = {
        Decisao.APROVADO_AUTO: "Todas as regras passaram, a identidade foi confirmada na base e os campos críticos têm confiança suficiente.",
        Decisao.AGUARDA_EMISSOR: "Registro consistente, mas há informação obrigatória que o próprio aviso declara pendente.",
        Decisao.REVISAO_HUMANA: "Há inconsistência, evidência insuficiente ou sinal de risco que exige conferência humana.",
        Decisao.FALHA_PROCESSAMENTO: "O documento não pôde ser processado.",
    }[escolhida.estado]
    pendente = escolhida.estado in (Decisao.REVISAO_HUMANA, Decisao.AGUARDA_EMISSOR)
    return DecisaoSaida(estado=escolhida.estado, resumo=resumo, motivos=motivos,
                        linha_da_tabela=f"{escolhida.id}: {escolhida.descricao}",
                        para_aprovar=para_aprovar(c) if pendente else None)
