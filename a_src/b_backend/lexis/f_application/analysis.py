"""Núcleo de análise (puro): extração(ões) + texto-fonte + base de referência -> RegistroSaida.

Não faz I/O nem chama modelo: tudo que entra é dado, tudo que sai é determinístico.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lexis.a_domain.models import (
    CampoSaida,
    Confianca,
    Decisao,
    EstadoCampo,
    Evidencia,
    Extracao,
    LeituraCampo,
    Nivel,
    RegistroSaida,
    RegraResultado,
    Severidade,
    Situacao,
    TipoEvento,
    ValidacaoGolden,
)
from lexis.a_domain.normalization import Normalizado, equivalentes, normalizar
from lexis.a_domain.ports import ChamadorDeTools, ConversaTools
from lexis.a_domain.specs import SPECS
from lexis.d_validation.classification import Classificacao, classificar
from lexis.d_validation.coherence import checar_formatos, resultado_de_regra
from lexis.d_validation.evidence import (
    corrobora,
    sinais_de_injecao,
    varrer_identificadores,
    verificar_citacao,
)
from lexis.d_validation.reference_base import Golden
from lexis.d_validation.tools import orquestrar
from lexis.e_decision.checklists import montar_fichas
from lexis.e_decision.confidence import EntradaConfianca, avaliar_confianca, min_nivel
from lexis.e_decision.decision_table import Contexto, decidir

CAMPOS_IDENTIDADE = {"emissor", "isin", "ticker", "cnpj", "classe_acao"}
REGRAS_QUE_CONFIRMAM = {
    "DATAS_EX_NAO_POSTERIOR_A_COM", "DATAS_PAGAMENTO_ANTES_DA_COM", "DATAS_PAGAMENTO_ANTES_DA_EX",
    "DATAS_CREDITO_ANTES_DA_COM", "TRIB_LIQUIDO_DIVERGE", "PROP_PERCENTUAL_DIVERGE",
    "PROP_SENTIDO_INCOMPATIVEL", "PROP_INVALIDA",
}
# Não confirmar o emissor na base não prova que a LEITURA esteja errada: rebaixa a MÉDIA, não a BAIXA.
REGRAS_SO_ALERTA_NO_CAMPO = {"GOLDEN_NAO_ENCONTRADO"}


@dataclass
class Leitura:
    extracao: Extracao
    fonte: str  # TEXTO_NATIVO | TRANSCRICAO_VISAO | LEITURA_DIRETA_VISAO
    paginas: list[tuple[int, str]]


@dataclass
class Entrada:
    run_id: str
    documento: dict[str, Any]
    versoes: dict[str, str]
    principal: Leitura
    golden: Golden
    texto_injecao: str
    avisos_ingestao: list[dict[str, str]] = field(default_factory=list)
    secundaria: Leitura | None = None
    scan: bool = False
    texto_ocr: str | None = None
    ocr_disponivel: bool = False
    bbox: Callable[[int, str], list[float] | None] | None = None
    chamador: ChamadorDeTools | None = None
    auditoria: dict[str, Any] = field(default_factory=dict)


@dataclass
class CampoInterno:
    nome: str
    estado: EstadoCampo
    norm: Normalizado | None = None
    texto: str | None = None
    pagina: int | None = None
    evidencia: Evidencia | None = None
    notas: list[str] = field(default_factory=list)


def _ler_campo(
    nome: str, lc: LeituraCampo | None, leitura: Leitura, regras: list[RegraResultado],
    bbox: Callable[[int, str], list[float] | None] | None,
) -> CampoInterno:
    lc = lc or LeituraCampo(situacao=Situacao.AUSENTE)
    if lc.situacao in (Situacao.AUSENTE, Situacao.NAO_APLICAVEL):
        return CampoInterno(nome, EstadoCampo.AUSENTE)
    achou, pagina = verificar_citacao(lc.texto or "", leitura.paginas, lc.pagina)
    if not achou:
        regras.append(resultado_de_regra(
            "EVIDENCIA_NAO_ENCONTRADA", False, [nome], SPECS.descricao("EVIDENCIA_NAO_ENCONTRADA"),
            observado=(lc.texto or "")[:80],
        ))
        return CampoInterno(nome, EstadoCampo.INCERTO, texto=lc.texto)
    caixa = bbox(pagina, lc.texto or "") if (bbox and pagina and leitura.fonte == "TEXTO_NATIVO") else None
    ev = Evidencia(pagina=pagina, trecho=lc.texto, bbox=caixa, fonte=leitura.fonte)
    if lc.situacao is Situacao.A_DEFINIR:
        return CampoInterno(nome, EstadoCampo.PENDENTE, texto=lc.texto, pagina=pagina, evidencia=ev)
    norm = normalizar(nome, lc.texto or "")
    if norm is None:
        regras.append(resultado_de_regra(
            "VALOR_NAO_INTERPRETAVEL", False, [nome], SPECS.descricao("VALOR_NAO_INTERPRETAVEL"),
            observado=(lc.texto or "")[:80],
        ))
        return CampoInterno(nome, EstadoCampo.INCERTO, texto=lc.texto, pagina=pagina, evidencia=ev)
    return CampoInterno(nome, EstadoCampo.EXTRAIDO, norm, lc.texto, pagina, ev)


def _citado(
    lc: LeituraCampo, leitura: Leitura, nome: str, regras: list[RegraResultado]
) -> tuple[str | None, Evidencia | None]:
    if lc.situacao is not Situacao.PRESENTE or not lc.texto:
        return None, None
    achou, pagina = verificar_citacao(lc.texto, leitura.paginas, lc.pagina)
    if not achou:
        regras.append(resultado_de_regra(
            "EVIDENCIA_NAO_ENCONTRADA", False, [nome], SPECS.descricao("EVIDENCIA_NAO_ENCONTRADA"),
            observado=lc.texto[:80],
        ))
        return None, None
    return lc.texto, Evidencia(pagina=pagina, trecho=lc.texto, fonte=leitura.fonte)


def analisar(e: Entrada) -> RegistroSaida:
    extr = e.principal.extracao
    regras: list[RegraResultado] = []

    # 1. Classificação do evento: sinais determinísticos × classificação do modelo
    titulo_txt, titulo_ev = _citado(extr.titulo, e.principal, "titulo", regras)
    campo_txt, campo_ev = _citado(extr.tipo_evento_texto, e.principal, "tipo_evento", regras)
    texto_completo = "\n".join(t for _, t in e.principal.paginas)
    cls: Classificacao = classificar(titulo_txt, campo_txt, texto_completo)
    tipo = cls.tipo
    regras.append(resultado_de_regra(
        "CLASSIFICACAO_DIVERGENTE", extr.tipo_evento == tipo, ["tipo_evento"],
        SPECS.descricao("CLASSIFICACAO_DIVERGENTE"),
        esperado=f"sinais do documento: {tipo.value}", observado=f"modelo: {extr.tipo_evento.value}",
    ))
    regras.append(resultado_de_regra(
        "TITULO_DIVERGE_CORPO", not cls.conflito_titulo_corpo, ["tipo_evento"],
        SPECS.descricao("TITULO_DIVERGE_CORPO"),
        esperado=f"tipo pelo corpo/natureza: {cls.por_zona.get('campo') or cls.por_zona.get('corpo')}",
        observado=f"tipo pelo título: {cls.por_zona.get('titulo')}",
    ))
    regras.append(resultado_de_regra(
        "TIPO_NAO_SUPORTADO", tipo is not TipoEvento.OUTRO, ["tipo_evento"], SPECS.descricao("TIPO_NAO_SUPORTADO")
    ))

    # 2. Campos: evidência verificada no texto-fonte e normalização pelo código
    campos = {n: _ler_campo(n, extr.campos.get(n), e.principal, regras, e.bbox) for n in SPECS.campos}

    # 3. Segunda leitura (scan): precisa concordar campo a campo
    concordam: dict[str, bool] = {}
    if e.secundaria is not None:
        sec_regras: list[RegraResultado] = []
        for n in SPECS.campos:
            b = _ler_campo(n, e.secundaria.extracao.campos.get(n), e.principal, sec_regras, None)
            a = campos[n]
            ok = a.estado == b.estado and (
                a.estado is not EstadoCampo.EXTRAIDO
                or (a.norm is not None and b.norm is not None and equivalentes(n, a.norm, b.norm))
            )
            concordam[n] = ok
            if not ok:
                regras.append(resultado_de_regra(
                    "SCAN_LEITURAS_DIVERGEM", False, [n], SPECS.descricao("SCAN_LEITURAS_DIVERGEM"),
                    esperado=f"leitura A: {a.estado.value} {a.norm.repr if a.norm else ''}".strip(),
                    observado=f"leitura B: {b.estado.value} {b.norm.repr if b.norm else ''}".strip(),
                ))
                if a.estado is EstadoCampo.EXTRAIDO:
                    a.estado = EstadoCampo.INCERTO
        if e.secundaria.extracao.tipo_evento != extr.tipo_evento:
            regras.append(resultado_de_regra(
                "SCAN_LEITURAS_DIVERGEM", False, ["tipo_evento"], SPECS.descricao("SCAN_LEITURAS_DIVERGEM"),
                esperado=f"leitura A: {extr.tipo_evento.value}", observado=f"leitura B: {e.secundaria.extracao.tipo_evento.value}",
            ))

    # 4. Aplicabilidade por tipo (matriz declarativa)
    pendentes: list[str] = []
    for n, c in campos.items():
        apl = SPECS.aplicabilidade(tipo.value, n)
        if apl == "nao_aplicavel" and c.estado in (EstadoCampo.AUSENTE, EstadoCampo.PENDENTE):
            c.estado = EstadoCampo.NAO_APLICAVEL
            c.evidencia = None
        elif apl == "nao_aplicavel" and c.estado is EstadoCampo.EXTRAIDO:
            c.notas.append("valor presente no aviso embora o campo não seja esperado para este tipo de evento")
        elif apl == "obrigatorio" and c.estado is EstadoCampo.AUSENTE:
            regras.append(resultado_de_regra(
                "CAMPO_OBRIGATORIO_AUSENTE", False, [n], SPECS.descricao("CAMPO_OBRIGATORIO_AUSENTE"),
                esperado=f"{SPECS.rotulos[n]} (obrigatório para {tipo.value})",
            ))
        elif apl == "obrigatorio" and c.estado is EstadoCampo.PENDENTE:
            pendentes.append(n)
            regras.append(resultado_de_regra(
                "CAMPO_PENDENTE_NO_AVISO", False, [n], SPECS.descricao("CAMPO_PENDENTE_NO_AVISO"),
                observado=c.texto,
            ))

    dados = {n: c.norm.valor for n, c in campos.items() if c.estado is EstadoCampo.EXTRAIDO and c.norm}

    # 5. OCR local como leitor independente do modelo
    ocr_por_campo: dict[str, bool | None] = {}
    if e.scan:
        if e.texto_ocr:
            for n, c in campos.items():
                if c.estado is EstadoCampo.EXTRAIDO and c.norm:
                    corr = corrobora(n, c.norm.valor, e.texto_ocr)
                    ocr_por_campo[n] = corr
                    if corr is False:
                        regras.append(resultado_de_regra(
                            "OCR_NAO_CORROBORA", False, [n], SPECS.descricao("OCR_NAO_CORROBORA"),
                            esperado=c.norm.repr, observado="valor não encontrado no texto do OCR",
                        ))
        else:
            regras.append(resultado_de_regra("OCR_INDISPONIVEL", False, [], SPECS.descricao("OCR_INDISPONIVEL")))

    # 6. Regras determinísticas via tools (function calling) + formatos
    regras += checar_formatos(dados)
    val = orquestrar(tipo, dados, e.golden, e.chamador)
    regras += val.regras
    golden: ValidacaoGolden = val.golden or ValidacaoGolden(status="NAO_AVALIADO")

    # 7. Identificadores presentes no texto e omitidos da extração
    ids = varrer_identificadores(texto_completo)
    extraidos = {str(dados.get(c)) for c in ("isin", "ticker", "cnpj") if dados.get(c)}
    faltando = sorted((ids.isins | ids.tickers | ids.cnpjs) - extraidos)
    regras.append(resultado_de_regra(
        "IDENTIFICADOR_NAO_EXTRAIDO", not faltando, [], SPECS.descricao("IDENTIFICADOR_NAO_EXTRAIDO"),
        observado=", ".join(faltando) or None,
    ))

    # 8. Sinais de segurança
    inj = sinais_de_injecao(e.texto_injecao)
    regras.append(resultado_de_regra("INJECAO_SUSPEITA", not inj, [], SPECS.descricao("INJECAO_SUSPEITA"),
                                     observado=", ".join(inj) or None))
    for codigo in ("TEXTO_OCULTO", "CONTEUDO_ATIVO_PDF"):
        achados = [a["detalhe"] for a in e.avisos_ingestao if a["codigo"] == codigo]
        regras.append(resultado_de_regra(codigo, not achados, [], SPECS.descricao(codigo),
                                         observado="; ".join(achados) or None))

    # 9. Confiança por campo
    erros: dict[str, list[str]] = {}
    avisos: dict[str, list[str]] = {}
    confirma: dict[str, list[str]] = {}
    for r in regras:
        for alvo in r.campos:
            if r.resultado == "FALHA" and r.severidade is Severidade.ERRO and r.id not in REGRAS_SO_ALERTA_NO_CAMPO:
                erros.setdefault(alvo, []).append(r.id)
            elif r.resultado == "FALHA" and r.severidade in (Severidade.AVISO, Severidade.ERRO):
                avisos.setdefault(alvo, []).append(r.id)
            elif r.resultado == "OK" and r.id in REGRAS_QUE_CONFIRMAM:
                confirma.setdefault(alvo, []).append(f"regra {r.id} satisfeita")
    comparados = {str(x["campo"]): x for x in golden.comparacoes}

    saida: dict[str, CampoSaida] = {}
    for n in SPECS.campos:
        c = campos[n]
        conf_extra = list(confirma.get(n, []))
        if golden.status == "MATCH" and n in CAMPOS_IDENTIDADE and comparados.get(n, {}).get("resultado") == "IGUAL":
            conf_extra.append("confirmado pela base de referência")
        nivel, motivos, just = avaliar_confianca(EntradaConfianca(
            campo=n, estado=c.estado, obrigatorio=SPECS.aplicabilidade(tipo.value, n) == "obrigatorio",
            fonte_scan=e.scan, pagina=c.pagina, regras_erro=erros.get(n, []), regras_aviso=avisos.get(n, []),
            confirmacoes=conf_extra, leituras_concordam=concordam.get(n) if e.secundaria else None,
            ocr=ocr_por_campo.get(n), ocr_disponivel=bool(e.texto_ocr),
        ))
        motivos += c.notas
        saida[n] = CampoSaida(
            estado=c.estado, valor=c.norm.repr if c.norm else None,
            detalhe_valor={k: v for k, v in (c.norm.detalhe if c.norm else {}).items() if v} or None,
            natureza="LITERAL" if c.estado is EstadoCampo.EXTRAIDO else None,
            texto_literal=c.texto, evidencia=c.evidencia,
            confianca=Confianca(nivel=nivel, motivos=motivos, justificativa=just),
        )

    tipo_campo = _campo_tipo(e, cls, extr.tipo_evento, titulo_ev, campo_ev, erros.get("tipo_evento", []))
    todos = {"tipo_evento": tipo_campo, **saida}

    # 10. Decisão
    ctx = Contexto(
        tipo=tipo.value, campos=todos, regras=regras,
        criticos=["tipo_evento", *SPECS.criticos(tipo.value)], obrigatorios_pendentes=pendentes,
    )
    decisao = decidir(ctx)
    fichas = montar_fichas(regras, todos)

    tratamento = {
        "descricao": SPECS.tipos[tipo.value]["tratamento_tributario"],
        "fonte_da_descricao": f"catálogo de regras v{SPECS.versao}",
        "observacao_literal_do_aviso": saida["observacao_tributaria"].texto_literal,
        "aliquota_irrf_informada": saida["aliquota_irrf"].detalhe_valor.get("percentual") if saida["aliquota_irrf"].detalhe_valor else None,
    }
    return RegistroSaida(
        run_id=e.run_id, documento=e.documento, versoes=e.versoes, decisao=decisao,
        evento={
            "tipo": tipo.value, "rotulo": SPECS.tipos[tipo.value]["rotulo"],
            "classificacao": {
                "tipo_final": tipo.value, "tipo_modelo": extr.tipo_evento.value, "por_zona": cls.por_zona,
                "pontuacao": cls.pontuacao, "sinais": cls.sinais, "conflito_titulo_corpo": cls.conflito_titulo_corpo,
            },
            "tratamento_tributario": tratamento,
        },
        campos=todos, validacao_golden=golden, regras=regras, fichas_conferencia=fichas,
        auditoria={**e.auditoria, "chamadas_de_tools": val.chamadas,
                   "validacao_pelo_modelo": _resumo_conversa(val.conversa)},
    )


def anexar_regra_e_redecidir(reg: RegistroSaida, regra: RegraResultado) -> None:
    """Regra que só se conhece depois da análise (duplicata no lote, modelo de fallback): entra no registro e a
    decisão e as fichas são refeitas pela mesma tabela. A confiança dos campos não muda (a regra não diz que a
    leitura esteja errada)."""
    reg.regras.append(regra)
    tipo = str(reg.evento.get("tipo", TipoEvento.OUTRO.value))
    pendentes = [r.campos[0] for r in reg.regras if r.id == "CAMPO_PENDENTE_NO_AVISO" and r.resultado == "FALHA" and r.campos]
    ctx = Contexto(tipo=tipo, campos=reg.campos, regras=reg.regras, criticos=["tipo_evento", *SPECS.criticos(tipo)],
                   obrigatorios_pendentes=pendentes)
    reg.decisao = decidir(ctx)
    reg.fichas_conferencia = montar_fichas(reg.regras, reg.campos)


def _resumo_conversa(c: ConversaTools | None) -> dict[str, Any] | None:
    """Como o function calling transcorreu. O parecer é do modelo e NÃO entra na decisão (só regras de código)."""
    if c is None:
        return None
    pedidas = [ch for t in c.turnos for ch in t.get("chamadas", [])]
    return {
        "turnos_com_tools": len(c.turnos),
        "tools_pedidas": [ch.get("tool") for ch in pedidas],
        "pedidos_rejeitados": sum(bool(ch.get("erro")) for ch in pedidas),
        "encerramento": c.encerramento,
        "parecer_do_modelo": c.parecer,
        "nota": "parecer informativo; o veredito de cada regra é o resultado da tool executada pelo código",
        "avisos": c.avisos,
    }


def _campo_tipo(
    e: Entrada, cls: Classificacao, tipo_modelo: TipoEvento, titulo_ev: Evidencia | None,
    campo_ev: Evidencia | None, regras_erro: list[str],
) -> CampoSaida:
    zonas = "; ".join(f"{z}={t or 'sem sinal'}" for z, t in cls.por_zona.items())
    motivos = [f"tipo inferido por sinais em cada zona do aviso ({zonas})"]
    if cls.tipo is TipoEvento.OUTRO:
        nivel = Nivel.BAIXA
        motivos.append("nenhum sinal suficiente para um tipo suportado")
    elif tipo_modelo != cls.tipo:
        nivel = Nivel.BAIXA
        motivos.append(f"modelo classificou como {tipo_modelo.value}, divergindo dos sinais")
    elif cls.conflito_titulo_corpo:
        nivel = Nivel.MEDIA
        motivos.append("título sugere outro tipo; prevalece o corpo/natureza do provento")
    else:
        nivel = Nivel.ALTA
        motivos.append("modelo e sinais do documento concordam")
    if e.scan:
        nivel = min_nivel(nivel, Nivel(SPECS.politica["teto_confianca_scan"]))
        motivos.append("fonte é imagem (scan): confiança limitada ao teto da política")
    if regras_erro:
        nivel = Nivel.BAIXA
        motivos.append("regra reprovada: " + ", ".join(sorted(set(regras_erro))))
    ev = campo_ev or titulo_ev
    return CampoSaida(
        estado=EstadoCampo.EXTRAIDO, valor=cls.tipo.value, natureza="DERIVADO",
        texto_literal=ev.trecho if ev else None, evidencia=ev,
        confianca=Confianca(nivel=nivel, motivos=motivos, justificativa=f"{nivel.value}: " + "; ".join(motivos) + "."),
    )


__all__ = ["Entrada", "Leitura", "analisar", "anexar_regra_e_redecidir", "Decisao"]
