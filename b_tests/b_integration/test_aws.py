import json
from pathlib import Path

import pytest

from b_tests.aws_fakes import S3Falso
from b_tests.conftest import DOCS, GOLDEN_CSV, REPLAY
from lexis.a_domain.ports import ChaveInvalida
from lexis.g_adapters.local_storage import ArmazenamentoLocal
from lexis.g_adapters.s3_storage import ArmazenamentoS3, ObjetoGrandeDemais
from lexis.h_interfaces.aws_lambda import ConfiguracaoInvalida, construir_contexto, handler

ENTRADA, SAIDA, REF = "bkt-entrada", "bkt-saida", "bkt-ref"
ENV = {
    "LEXIS_BUCKET_ENTRADA": ENTRADA, "LEXIS_BUCKET_SAIDA": SAIDA, "LEXIS_BUCKET_REFERENCIA": REF,
    "LEXIS_CHAVE_GOLDEN": "golden_records.csv", "LEXIS_MODO": "replay", "LEXIS_KMS_KEY_ID": "alias/lexis",
}


@pytest.fixture(autouse=True)
def _sem_contexto_global(monkeypatch):
    """O handler reaproveita o contexto entre invocações; cada teste precisa começar sem cache."""
    monkeypatch.setattr("lexis.h_interfaces.aws_lambda._CONTEXTO", None)


@pytest.fixture
def s3() -> S3Falso:
    c = S3Falso()
    c.put(REF, "golden_records.csv", GOLDEN_CSV.read_bytes())
    for arq in Path(REPLAY).rglob("*.json"):  # gravações endereçadas por sha: <sha>/<etapa>.json
        c.put(SAIDA, "gravacoes/" + arq.relative_to(REPLAY).as_posix(), arq.read_bytes())
    for pdf in DOCS.glob("*.pdf"):
        c.put(ENTRADA, f"avisos/{pdf.name}", pdf.read_bytes())
    return c


def evento_s3(chave: str, bucket: str = ENTRADA) -> dict:
    return {"Records": [{"eventSource": "aws:s3", "s3": {"bucket": {"name": bucket}, "object": {"key": chave}}}]}


def evento_sqs(chave: str, id_msg: str = "m1") -> dict:
    corpo = json.dumps(evento_s3(chave))
    return {"Records": [{"eventSource": "aws:sqs", "messageId": id_msg, "body": corpo}]}


# --------------------------------------------------------------------------- adaptador S3


def test_s3_roundtrip_listar_e_ler_inexistente(s3):
    arm = ArmazenamentoS3(SAIDA, "pref", cliente=s3, kms_key_id="alias/k")
    arm.gravar("a/b.json", b"x")
    assert arm.ler("a/b.json") == b"x" and arm.ler("nao-existe") is None
    assert (SAIDA, "pref/a/b.json") in s3.objetos
    assert arm.listar("a/") == ["a/b.json"]
    assert s3.escritas[-1]["ServerSideEncryption"] == "aws:kms" and s3.escritas[-1]["SSEKMSKeyId"] == "alias/k"


def test_s3_pagina_a_listagem(s3):
    arm = ArmazenamentoS3(SAIDA, "gravacoes", cliente=s3)
    assert len(arm.listar()) == len(list(REPLAY.rglob("*.json")))  # várias páginas de 2 itens


def test_s3_rejeita_chaves_que_escapam_do_prefixo(s3):
    arm = ArmazenamentoS3(SAIDA, "p", cliente=s3)
    for ruim in ("../outro", "/abs", "a/../../b", "", "x\x00y"):
        with pytest.raises(ChaveInvalida):
            arm.ler(ruim)


def test_s3_limite_de_tamanho_antes_de_baixar(s3):
    s3.put(ENTRADA, "grande.pdf", b"0" * 100)
    with pytest.raises(ObjetoGrandeDemais):
        ArmazenamentoS3(ENTRADA, cliente=s3, limite_bytes=10).ler("grande.pdf")


def test_s3_propaga_erros_que_nao_sao_ausencia(s3):
    s3.falhar_leitura = True
    with pytest.raises(Exception, match="SlowDown"):
        ArmazenamentoS3(ENTRADA, cliente=s3).ler("x")


def test_local_e_s3_rejeitam_o_mesmo_tipo_de_chave(tmp_path):
    with pytest.raises(ChaveInvalida):
        ArmazenamentoLocal(tmp_path).ler("../fora")


# --------------------------------------------------------------------------- handler Lambda


def test_handler_processa_documento_e_grava_json_no_bucket_de_saida(s3):
    r = handler(evento_s3("avisos/05_aurora_saneamento_dividendo_datas.pdf"), env=ENV, s3=s3)
    assert r["processados"] == [{"arquivo": "avisos/05_aurora_saneamento_dividendo_datas.pdf",
                                 "decisao": "REVISAO_HUMANA", "disposicao": "PROCESSADO"}]
    saida = json.loads(s3.objetos[(SAIDA, "json/avisos/05_aurora_saneamento_dividendo_datas.json")])  # preserva o diretório
    assert saida["decisao"]["estado"] == "REVISAO_HUMANA"
    assert any(e.get("ServerSideEncryption") == "aws:kms" for e in s3.escritas)  # saída criptografada com KMS


def test_handler_e_idempotente_na_reentrega(s3):
    ev = evento_s3("avisos/02_banco_meridional_jcp.pdf")
    assert handler(ev, env=ENV, s3=s3)["processados"][0]["disposicao"] == "PROCESSADO"
    assert handler(ev, env=ENV, s3=s3)["processados"][0]["disposicao"] == "REUTILIZADO"  # at-least-once não duplica


def test_handler_rejeita_evento_de_bucket_nao_configurado(s3):
    r = handler(evento_s3("avisos/02_banco_meridional_jcp.pdf", bucket="bucket-do-atacante"), env=ENV, s3=s3)
    assert r["processados"] == []
    assert not any(b == SAIDA and k.startswith("json/") for (b, k) in s3.objetos)


def test_handler_pdf_invalido_vira_falha_explicita_sem_derrubar(s3):
    s3.put(ENTRADA, "avisos/lixo.pdf", b"isto nao e pdf")
    r = handler(evento_s3("avisos/lixo.pdf"), env=ENV, s3=s3)
    assert r["processados"][0]["decisao"] == "FALHA_PROCESSAMENTO"


def test_handler_objeto_acima_do_limite_vira_falha_sem_baixar_o_corpo(s3, monkeypatch):
    monkeypatch.setattr("lexis.h_interfaces.aws_lambda.MAX_BYTES", 10)
    r = handler(evento_s3("avisos/02_banco_meridional_jcp.pdf"), env=ENV, s3=s3)
    assert r["processados"][0]["decisao"] == "FALHA_PROCESSAMENTO"


def test_handler_sqs_devolve_item_com_falha_de_infra_para_reentrega(s3):
    ctx = construir_contexto(ENV, s3)
    s3.falhar_leitura = True  # S3 indisponível: a mensagem deve voltar à fila (e à DLQ), não ser perdida
    r = handler(evento_sqs("avisos/02_banco_meridional_jcp.pdf", "msg-42"), env=ENV, s3=s3, contexto=ctx)
    assert r["batchItemFailures"] == [{"itemIdentifier": "msg-42"}] and r["processados"] == []


def test_handler_evento_s3_direto_propaga_falha_de_infra(s3):
    ctx = construir_contexto(ENV, s3)
    s3.falhar_leitura = True
    with pytest.raises(Exception, match="SlowDown"):
        handler(evento_s3("avisos/02_banco_meridional_jcp.pdf"), env=ENV, s3=s3, contexto=ctx)


def test_configuracao_obrigatoria_ausente_falha_cedo(s3):
    with pytest.raises(ConfiguracaoInvalida):
        construir_contexto({"LEXIS_BUCKET_SAIDA": SAIDA}, s3)


def test_nenhum_segredo_ou_texto_do_documento_na_trilha_do_handler(s3, capsys):
    handler(evento_s3("avisos/01_energetica_vale_tiete_dividendo.pdf"), env=ENV, s3=s3)
    out = capsys.readouterr().out
    assert '"evento": "doc_concluido"' in out
    for proibido in ("Marcos Antônio", "0,4275000000", "BRTIETACNOR3"):
        assert proibido not in out
