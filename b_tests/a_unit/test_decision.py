from lexis.a_domain.models import (
    CampoSaida,
    Confianca,
    Decisao,
    EstadoCampo,
    Nivel,
    RegraResultado,
    Severidade,
)
from lexis.a_domain.specs import SPECS
from lexis.e_decision.confidence import EntradaConfianca, avaliar_confianca
from lexis.e_decision.decision_table import TABELA, Contexto, decidir


def campo(estado=EstadoCampo.EXTRAIDO, nivel=Nivel.ALTA) -> CampoSaida:
    return CampoSaida(estado=estado, valor="x", confianca=Confianca(nivel=nivel, motivos=[], justificativa=""))


def regra(id_, sev, resultado="FALHA", campos=()) -> RegraResultado:
    return RegraResultado(id=id_, severidade=sev, resultado=resultado, campos=list(campos), detalhe=id_)


def ctx(regras=(), campos=None, pendentes=()) -> Contexto:
    base = {"isin": campo(), "data_com": campo(), "tipo_evento": campo()}
    base.update(campos or {})
    return Contexto(tipo="JCP", campos=base, regras=list(regras), criticos=["tipo_evento", "isin", "data_com"],
                    obrigatorios_pendentes=list(pendentes))


def estado(c: Contexto) -> tuple[Decisao, str]:
    d = decidir(c)
    return d.estado, d.linha_da_tabela.split(":")[0]


# uma asserção por linha da tabela de decisão
def test_l1_sinal_de_seguranca():
    assert estado(ctx([regra("INJECAO_SUSPEITA", Severidade.AVISO)])) == (Decisao.REVISAO_HUMANA, "L1")
    assert estado(ctx([regra("TEXTO_OCULTO", Severidade.AVISO)]))[1] == "L1"
    assert estado(ctx([regra("CONTEUDO_ATIVO_PDF", Severidade.AVISO)]))[1] == "L1"


def test_l2_qualquer_erro_de_regra():
    assert estado(ctx([regra("GOLDEN_NAO_ENCONTRADO", Severidade.ERRO)])) == (Decisao.REVISAO_HUMANA, "L2")


def test_l3_titulo_diverge_do_corpo():
    assert estado(ctx([regra("TITULO_DIVERGE_CORPO", Severidade.AVISO)])) == (Decisao.REVISAO_HUMANA, "L3")


def test_l4_campo_critico_ausente_incerto_ou_fraco():
    assert estado(ctx(campos={"isin": campo(EstadoCampo.AUSENTE)}))[1] == "L4"
    assert estado(ctx(campos={"isin": campo(EstadoCampo.INCERTO, Nivel.BAIXA)}))[1] == "L4"
    assert estado(ctx(campos={"data_com": campo(nivel=Nivel.BAIXA)}))[1] == "L4"


# ------------------------------------------------------------------ o que falta para aprovar
def passos(c: Contexto) -> list[tuple[str, str | None, str, str]]:
    p = decidir(c).para_aprovar
    assert p is not None
    return [(x.codigo, x.campo, x.linha_que_aciona, x.linha_se_so_este_resolver) for x in p.passos]


def test_aprovado_nao_tem_o_que_falta():
    assert decidir(ctx()).para_aprovar is None


def test_um_bloqueio_que_sozinho_aprova():
    c = ctx([regra("GOLDEN_NAO_ENCONTRADO", Severidade.ERRO, campos=["isin"])])
    assert passos(c) == [("GOLDEN_NAO_ENCONTRADO", "isin", "L2", "L7")]
    para = decidir(c).para_aprovar
    assert para is not None and para.decisao_com_todos_resolvidos is Decisao.APROVADO_AUTO


def test_dois_bloqueios_nenhum_basta_sozinho_e_juntos_aprovam():
    # como o doc 05: duas regras no mesmo campo; o rebaixamento a BAIXA é consequência delas, não um passo a mais
    c = ctx([regra("DATAS_PAGAMENTO_ANTES_DA_COM", Severidade.ERRO, campos=["data_com"]),
             regra("DATAS_PAGAMENTO_ANTES_DA_EX", Severidade.ERRO, campos=["data_com"])],
            campos={"data_com": campo(nivel=Nivel.BAIXA)})
    assert passos(c) == [("DATAS_PAGAMENTO_ANTES_DA_COM", "data_com", "L2", "L2"),
                         ("DATAS_PAGAMENTO_ANTES_DA_EX", "data_com", "L2", "L2")]
    para = decidir(c).para_aprovar
    assert para is not None and (para.decisao_com_todos_resolvidos, para.linha_com_todos_resolvidos) == (
        Decisao.APROVADO_AUTO, "L7")


def test_campo_fraco_sem_regra_e_um_passo_proprio_e_resolver_outro_nao_basta():
    c = ctx([regra("GOLDEN_NAO_ENCONTRADO", Severidade.ERRO, campos=["isin"])],
            campos={"data_com": campo(EstadoCampo.INCERTO, Nivel.BAIXA)})
    assert passos(c) == [("GOLDEN_NAO_ENCONTRADO", "isin", "L2", "L4"), ("CAMPO_CRITICO_FRACO", "data_com", "L4", "L2")]


def test_politicas_e_pendencia_viram_passos_com_a_linha_certa():
    assert passos(ctx([regra("TITULO_DIVERGE_CORPO", Severidade.AVISO, campos=["tipo_evento"])])) == [
        ("TITULO_DIVERGE_CORPO", "tipo_evento", "L3", "L7")]
    assert passos(ctx([regra("OCR_INDISPONIVEL", Severidade.INFO)])) == [("OCR_INDISPONIVEL", None, "L5", "L7")]
    assert passos(ctx([regra("TEXTO_OCULTO", Severidade.AVISO)])) == [("TEXTO_OCULTO", None, "L1", "L7")]
    pendente = ctx(campos={"data_pagamento": campo(EstadoCampo.PENDENTE)}, pendentes=["data_pagamento"])
    assert passos(pendente) == [("CAMPO_PENDENTE_NO_AVISO", "data_pagamento", "L6", "L7")]


def test_campo_critico_com_confianca_media_e_aceito():
    assert estado(ctx(campos={"data_com": campo(nivel=Nivel.MEDIA)})) == (Decisao.APROVADO_AUTO, "L7")


def test_l5_scan_sem_ocr_independente_vai_para_revisao():
    d = decidir(ctx([regra("OCR_INDISPONIVEL", Severidade.INFO)]))
    assert (d.estado, d.linha_da_tabela.split(":")[0]) == (Decisao.REVISAO_HUMANA, "L5")
    assert "OCR_INDISPONIVEL" in {m.codigo for m in d.motivos}
    # OCR disponível (a regra não falha): o scan segue o caminho normal
    assert estado(ctx([regra("OCR_INDISPONIVEL", Severidade.INFO, "OK")])) == (Decisao.APROVADO_AUTO, "L7")


def test_l5_respeita_a_politica(monkeypatch):
    monkeypatch.setitem(SPECS.politica, "revisao_scan_sem_ocr_independente", False)
    assert estado(ctx([regra("OCR_INDISPONIVEL", Severidade.INFO)])) == (Decisao.APROVADO_AUTO, "L7")


def test_l6_pendente_aguarda_emissor():
    assert estado(ctx(campos={"data_pagamento": campo(EstadoCampo.PENDENTE)}, pendentes=["data_pagamento"])) == (
        Decisao.AGUARDA_EMISSOR, "L6")


def test_l7_aprovado_quando_nada_falha():
    assert estado(ctx()) == (Decisao.APROVADO_AUTO, "L7")


def test_avisos_comuns_nao_bloqueiam():
    assert estado(ctx([regra("DATA_FIM_DE_SEMANA", Severidade.AVISO)]))[1] == "L7"


def test_regra_ok_ou_nao_aplicavel_nao_conta_como_falha():
    assert estado(ctx([regra("GOLDEN_NAO_ENCONTRADO", Severidade.ERRO, "OK")])) == (Decisao.APROVADO_AUTO, "L7")


def test_precedencia_seguranca_vence_erro_vence_pendente():
    c = ctx([regra("INJECAO_SUSPEITA", Severidade.AVISO), regra("GOLDEN_NAO_ENCONTRADO", Severidade.ERRO)],
            pendentes=["data_pagamento"])
    d = decidir(c)
    assert d.linha_da_tabela.startswith("L1")
    assert {"INJECAO_SUSPEITA", "GOLDEN_NAO_ENCONTRADO", "CAMPO_PENDENTE_NO_AVISO"} <= {m.codigo for m in d.motivos}


def test_pendente_com_erro_vira_revisao_e_mantem_o_motivo_pendente():
    d = decidir(ctx([regra("DATAS_PAGAMENTO_ANTES_DA_COM", Severidade.ERRO)], pendentes=["data_pagamento"]))
    assert d.estado is Decisao.REVISAO_HUMANA
    assert "CAMPO_PENDENTE_NO_AVISO" in {m.codigo for m in d.motivos}


def test_tabela_termina_em_linha_universal():
    assert TABELA[-1].condicao(ctx()) and TABELA[-1].estado is Decisao.APROVADO_AUTO


# ----------------------------------------------------------------- confiança


def entrada(**kw) -> EntradaConfianca:
    base = dict(campo="valor_bruto", estado=EstadoCampo.EXTRAIDO, obrigatorio=True, fonte_scan=False, pagina=1,
                regras_erro=[], regras_aviso=[], confirmacoes=[])
    base.update(kw)
    return EntradaConfianca(**base)


def test_extraido_e_verificado_tem_confianca_alta_com_justificativa():
    nivel, motivos, just = avaliar_confianca(entrada(confirmacoes=["confirmado pela base de referência"]))
    assert nivel is Nivel.ALTA and "confirmado pela base de referência" in motivos and just.startswith("ALTA")


def test_scan_tem_teto_media_mesmo_com_tudo_certo():
    nivel, motivos, _ = avaliar_confianca(entrada(fonte_scan=True, leituras_concordam=True, ocr=True, ocr_disponivel=True))
    assert nivel is Nivel.MEDIA and any("duas leituras" in m for m in motivos)


def test_regra_de_erro_derruba_para_baixa_e_aviso_para_media():
    assert avaliar_confianca(entrada(regras_erro=["TRIB_LIQUIDO_DIVERGE"]))[0] is Nivel.BAIXA
    assert avaliar_confianca(entrada(regras_aviso=["DATA_FIM_DE_SEMANA"]))[0] is Nivel.MEDIA


def test_estados_nao_extraidos():
    assert avaliar_confianca(entrada(estado=EstadoCampo.PENDENTE))[0] is Nivel.ALTA
    assert avaliar_confianca(entrada(estado=EstadoCampo.NAO_APLICAVEL))[0] is Nivel.ALTA
    assert avaliar_confianca(entrada(estado=EstadoCampo.AUSENTE, obrigatorio=True))[0] is Nivel.BAIXA
    assert avaliar_confianca(entrada(estado=EstadoCampo.AUSENTE, obrigatorio=False))[0] is Nivel.MEDIA
    assert avaliar_confianca(entrada(estado=EstadoCampo.INCERTO))[0] is Nivel.BAIXA
