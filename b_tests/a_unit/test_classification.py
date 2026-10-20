from b_tests.conftest import extracao_replay, texto_do_pdf
from lexis.a_domain.models import TipoEvento
from lexis.d_validation.classification import classificar


def _cls(stem: str):
    e = extracao_replay(stem)
    return classificar(e.titulo.texto, e.tipo_evento_texto.texto, texto_do_pdf(stem))


def test_jcp_que_cita_dividendo_obrigatorio_continua_jcp():  # doc 02: "imputado aos dividendos obrigatórios"
    c = _cls("02_banco_meridional_jcp")
    assert c.tipo is TipoEvento.JCP and not c.conflito_titulo_corpo


def test_titulo_dividendos_com_corpo_de_jcp_prevalece_o_corpo_e_sinaliza():  # doc 03
    c = _cls("03_siderurgica_paranaense_proventos")
    assert c.tipo is TipoEvento.JCP
    assert c.por_zona["titulo"] == "DIVIDENDO"
    assert c.conflito_titulo_corpo


def test_dividendo_comum_e_intercalar():
    assert _cls("01_energetica_vale_tiete_dividendo").tipo is TipoEvento.DIVIDENDO
    assert _cls("05_aurora_saneamento_dividendo_datas").tipo is TipoEvento.DIVIDENDO


def test_grupamento_e_bonificacao():
    assert _cls("06_petroquimica_litoral_grupamento").tipo is TipoEvento.GRUPAMENTO
    assert _cls("08_construtora_horizonte_bonificacao").tipo is TipoEvento.BONIFICACAO


def test_scan_transcrito_e_jcp():
    import json

    from b_tests.conftest import DOCS, REPLAY
    from lexis.g_adapters.local_execution import ingerir_arquivo

    stem = "07_telecom_norte_jcp_SCAN"
    e = extracao_replay(stem, "extracao_transcricao")
    sha = ingerir_arquivo(DOCS / f"{stem}.pdf").sha256
    texto = json.loads((REPLAY / sha / "transcricao.json").read_text(encoding="utf-8"))["conteudo"]["texto"]
    assert classificar(e.titulo.texto, e.tipo_evento_texto.texto, texto).tipo is TipoEvento.JCP


def test_sem_sinal_vira_outro_e_empate_nao_escolhe_no_chute():
    assert classificar(None, None, "Comunicado sobre reunião ordinária.").tipo is TipoEvento.OUTRO
    c = classificar(None, None, "grupamento de ações e também bonificação em ações")
    assert c.tipo is TipoEvento.OUTRO


def test_desdobramento():
    assert classificar("Desdobramento de ações", None, "desdobramento na proporção de 1:2").tipo is TipoEvento.DESDOBRAMENTO
