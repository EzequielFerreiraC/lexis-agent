import json
import shutil

from b_tests.conftest import DOCS, REPLAY
from lexis.a_domain.models import Decisao, RegistroSaida
from lexis.f_application.batch import _anexar_duplicatas_de_evento, processar_lote
from lexis.f_application.report import publicar_relatorios, resumo_para_aprovar
from lexis.g_adapters.local_execution import executar_lote, processar_documento
from lexis.g_adapters.local_storage import ArmazenamentoLocal, ArmazenamentoMemoria
from lexis.g_adapters.local_trail import TrilhaMemoria


def test_replay_reproduz_extracao_e_function_calling_reais_do_modelo(ctx):
    """As gravações são respostas reais (origem API) e, em replay, toda tool aceita foi pedida pelo MODELO."""
    for pdf in sorted(DOCS.glob("*.pdf")):
        reg = processar_documento(pdf, ctx, "t")
        llm = reg.auditoria["chamadas_llm"]
        assert llm and all(c["origem"] == "CACHE" and c["origem_fixture"] == "API" for c in llm), pdf.name
        assert any(c["etapa"] == "validacao_tools" for c in llm), pdf.name
        aceitas = [c for c in reg.auditoria["chamadas_de_tools"] if c["aceita"]]
        assert aceitas and {c["origem"] for c in aceitas} == {"MODELO"}, pdf.name
        conversa = reg.auditoria["validacao_pelo_modelo"]
        assert conversa["encerramento"] == "end_turn" and conversa["avisos"] == [], pdf.name
        assert conversa["parecer_do_modelo"], pdf.name


def test_armadilhas_do_lote_tem_motivo_e_ficha(ctx):
    doc03 = processar_documento(DOCS / "03_siderurgica_paranaense_proventos.pdf", ctx, "t")
    assert doc03.decisao.motivos[0].codigo == "TITULO_DIVERGE_CORPO"
    assert doc03.fichas_conferencia[0].tipo_acao.value == "CONFERIR_CLASSIFICACAO"
    doc04 = processar_documento(DOCS / "04_rede_varejo_jcp_sem_data.pdf", ctx, "t")
    assert doc04.campos["data_pagamento"].estado.value == "PENDENTE" and doc04.campos["data_pagamento"].valor is None
    assert doc04.fichas_conferencia[0].tipo_acao.value == "AGUARDAR_AVISO_COMPLEMENTAR"
    doc05 = processar_documento(DOCS / "05_aurora_saneamento_dividendo_datas.pdf", ctx, "t")
    assert {f.codigo for f in doc05.fichas_conferencia} >= {"DATAS_PAGAMENTO_ANTES_DA_COM"}
    doc08 = processar_documento(DOCS / "08_construtora_horizonte_bonificacao.pdf", ctx, "t")
    assert doc08.fichas_conferencia[0].tipo_acao.value == "CADASTRAR_EMISSOR"


def test_doc01_nao_calcula_liquido_nem_assume_aliquota(ctx):
    r = processar_documento(DOCS / "01_energetica_vale_tiete_dividendo.pdf", ctx, "t")
    assert r.campos["valor_liquido"].valor is None and r.campos["aliquota_irrf"].valor is None
    assert "50.000,00" in (r.campos["observacao_tributaria"].texto_literal or "")


def test_grupamento_nao_cobra_data_de_pagamento_nem_valor(ctx):
    r = processar_documento(DOCS / "06_petroquimica_litoral_grupamento.pdf", ctx, "t")
    for c in ("data_pagamento", "valor_bruto", "moeda"):
        assert r.campos[c].estado.value == "NAO_APLICAVEL"
    assert r.campos["proporcao"].detalhe_valor["termo_a"] == "10"


def test_bonificacao_custo_atribuido_nao_e_valor_de_provento(ctx):
    r = processar_documento(DOCS / "08_construtora_horizonte_bonificacao.pdf", ctx, "t")
    assert r.campos["valor_bruto"].estado.value == "NAO_APLICAVEL"
    assert r.campos["custo_atribuido"].valor == "7.820000"


def test_scan_sem_ocr_tem_teto_media_e_vai_para_revisao(ctx):
    r = processar_documento(DOCS / "07_telecom_norte_jcp_SCAN.pdf", ctx, "t")
    assert r.documento["fonte"] == "SCAN"
    niveis = {c.confianca.nivel.value for c in r.campos.values() if c.estado.value == "EXTRAIDO"}
    assert niveis == {"MEDIA"}
    assert any(x.id == "OCR_INDISPONIVEL" for x in r.regras if x.resultado == "FALHA")
    assert r.decisao.estado.value == "REVISAO_HUMANA" and r.decisao.linha_da_tabela.startswith("L5")
    assert [m.codigo for m in r.decisao.motivos] == ["OCR_INDISPONIVEL"]
    ficha = next(f for f in r.fichas_conferencia if f.codigo == "OCR_INDISPONIVEL")
    assert "imagem da página" in ficha.acao_sugerida


def test_scan_com_ocr_gravado_que_corrobora_segue_o_caminho_normal_com_teto_media(ctx_entrega):
    r = processar_documento(DOCS / "07_telecom_norte_jcp_SCAN.pdf", ctx_entrega, "t")
    extraidos = {n: c for n, c in r.campos.items() if c.estado.value == "EXTRAIDO"}
    assert {c.confianca.nivel.value for c in extraidos.values()} == {"MEDIA"}  # o teto do scan continua valendo
    assert not any(x.id in {"OCR_INDISPONIVEL", "OCR_NAO_CORROBORA"} for x in r.regras if x.resultado == "FALHA")
    for campo in ("isin", "data_com", "data_pagamento", "valor_bruto", "valor_liquido"):
        assert "OCR local corrobora o valor" in extraidos[campo].confianca.motivos, campo
    assert r.decisao.estado.value == "APROVADO_AUTO" and r.decisao.linha_da_tabela.startswith("L7")


def test_o_que_falta_para_aprovar_em_cada_excecao_do_lote(ctx_entrega):
    esperado = {
        "03_siderurgica_paranaense_proventos": [("TITULO_DIVERGE_CORPO", "L7")],
        "04_rede_varejo_jcp_sem_data": [("CAMPO_PENDENTE_NO_AVISO", "L7")],
        # duas regras no mesmo campo: nenhuma basta sozinha
        "05_aurora_saneamento_dividendo_datas": [("DATAS_PAGAMENTO_ANTES_DA_COM", "L2"), ("DATAS_PAGAMENTO_ANTES_DA_EX", "L2")],
        "08_construtora_horizonte_bonificacao": [("GOLDEN_NAO_ENCONTRADO", "L7")],
    }
    for stem, passos in esperado.items():
        para = processar_documento(DOCS / f"{stem}.pdf", ctx_entrega, "t").decisao.para_aprovar
        assert para is not None, stem
        assert [(p.codigo, p.linha_se_so_este_resolver) for p in para.passos] == passos, stem
        assert para.decisao_com_todos_resolvidos is Decisao.APROVADO_AUTO, stem
    assert processar_documento(DOCS / "01_energetica_vale_tiete_dividendo.pdf", ctx_entrega, "t").decisao.para_aprovar is None

    # no relatório de exceções, uma linha por documento: o que basta sozinho ou o que precisa ir junto
    r05 = processar_documento(DOCS / "05_aurora_saneamento_dividendo_datas.pdf", ctx_entrega, "t")
    r08 = processar_documento(DOCS / "08_construtora_horizonte_bonificacao.pdf", ctx_entrega, "t")
    assert resumo_para_aprovar(r05) == "resolver juntos `DATAS_PAGAMENTO_ANTES_DA_COM` + `DATAS_PAGAMENTO_ANTES_DA_EX`"
    assert resumo_para_aprovar(r08) == "basta resolver `GOLDEN_NAO_ENCONTRADO`"


def test_toda_evidencia_extraida_tem_pagina_e_trecho(ctx):
    for pdf in sorted(DOCS.glob("0[1-68]*.pdf")):
        r = processar_documento(pdf, ctx, "t")
        for nome, c in r.campos.items():
            if c.estado.value == "EXTRAIDO":
                assert c.evidencia and c.evidencia.pagina == 1 and c.evidencia.trecho, f"{pdf.name}:{nome}"
                assert c.confianca.justificativa and c.confianca.motivos


def test_saida_valida_contra_o_schema_estrito(ctx):
    r = processar_documento(DOCS / "02_banco_meridional_jcp.pdf", ctx, "t")
    assert RegistroSaida.model_validate_json(json.dumps(r.model_dump(mode="json"))) == r
    assert r.schema_version == "1.1" and r.versoes["golden_sha"] and r.versoes["regras"]


def test_lote_completo_idempotencia_duplicata_e_falha(ctx, tmp_path):
    entrada = tmp_path / "in"
    entrada.mkdir()
    for p in DOCS.glob("0[1-3]*.pdf"):
        shutil.copy(p, entrada / p.name)
    shutil.copy(DOCS / "01_energetica_vale_tiete_dividendo.pdf", entrada / "01_copia_identica.pdf")
    (entrada / "zz_corrompido.pdf").write_bytes(b"%PDF-1.4 lixo")
    # copiar também as gravações não é necessário: a gravação é localizada pelo sha do conteúdo
    saida = tmp_path / "out"

    res, run_id = executar_lote(entrada, saida, ctx)
    por_nome = {n: (r, d) for n, r, d in res}
    gemeos = {por_nome["01_copia_identica.pdf"][1], por_nome["01_energetica_vale_tiete_dividendo.pdf"][1]}
    assert gemeos == {"PROCESSADO", "DUPLICADO_NO_LOTE"}  # mesmo conteúdo, nomes diferentes: processa uma vez
    assert por_nome["01_copia_identica.pdf"][0].decisao.estado is Decisao.APROVADO_AUTO  # achou a gravação pelo sha
    assert por_nome["zz_corrompido.pdf"][0].decisao.estado is Decisao.FALHA_PROCESSAMENTO
    assert por_nome["02_banco_meridional_jcp.pdf"][0].decisao.estado is Decisao.APROVADO_AUTO  # um erro não derruba o lote
    assert (saida / "json" / "02_banco_meridional_jcp.json").exists()

    res2, _ = executar_lote(entrada, saida, ctx)
    assert {n: d for n, _, d in res2}["02_banco_meridional_jcp.pdf"] == "REUTILIZADO"
    res3, _ = executar_lote(entrada, saida, ctx, forcar=True)
    assert {n: d for n, _, d in res3}["02_banco_meridional_jcp.pdf"] == "PROCESSADO"

    publicar_relatorios(ArmazenamentoLocal(saida), res, run_id)
    md = (saida / "relatorio_excecoes.md").read_text(encoding="utf-8")
    assert len(md.splitlines()) <= 40 and "03_siderurgica" in md  # relatório curto
    assert json.loads((saida / "resumo_execucao.json").read_text(encoding="utf-8"))["extracoes_simuladas"] is False
    assert "simuladas" not in md


def test_cache_entre_execucoes_reaproveita_e_completa_a_pasta_nova(ctx, tmp_path):
    entrada = tmp_path / "in"
    entrada.mkdir()
    shutil.copy(DOCS / "02_banco_meridional_jcp.pdf", entrada)
    cache = tmp_path / "_cache"

    res1, _ = executar_lote(entrada, tmp_path / "report_1", ctx, cache=cache)
    assert {d for _, _, d in res1} == {"PROCESSADO"}
    res2, _ = executar_lote(entrada, tmp_path / "report_2", ctx, cache=cache)
    assert {d for _, _, d in res2} == {"REUTILIZADO"}
    assert (tmp_path / "report_2" / "json" / "02_banco_meridional_jcp.json").exists()  # pasta nova fica completa
    res3, _ = executar_lote(entrada, tmp_path / "report_3", ctx, forcar=True, cache=cache)
    assert {d for _, _, d in res3} == {"PROCESSADO"}


def test_trilha_de_auditoria_nao_contem_texto_do_documento(ctx, tmp_path):
    entrada = tmp_path / "in"
    entrada.mkdir()
    shutil.copy(DOCS / "01_energetica_vale_tiete_dividendo.pdf", entrada)
    executar_lote(entrada, tmp_path / "out", ctx)
    trilha = (tmp_path / "out" / "auditoria.jsonl").read_text(encoding="utf-8")
    for proibido in ("Marcos Antônio", "Diretor de Relações", "0,4275000000", "BRTIETACNOR3"):
        assert proibido not in trilha
    eventos = [json.loads(linha)["evento"] for linha in trilha.splitlines()]
    assert eventos[0] == "run_inicio" and eventos[-1] == "run_fim" and "doc_concluido" in eventos


def test_duplicata_de_evento_em_arquivos_diferentes_vai_a_revisao(ctx, tmp_path):
    # mesmo evento (ISIN + tipo + data com), PDFs com bytes distintos: o sha não pega, a chave do evento sim
    a = processar_documento(DOCS / "02_banco_meridional_jcp.pdf", ctx, "t")
    assert a.decisao.estado is Decisao.APROVADO_AUTO
    b = a.model_copy(deep=True)
    resultados = [("a.pdf", a, "PROCESSADO"), ("b.pdf", b, "PROCESSADO")]
    assert _anexar_duplicatas_de_evento(resultados) == {"a.pdf", "b.pdf"}
    for r in (a, b):  # aprovar os dois lançaria o evento em dobro
        assert r.decisao.estado is Decisao.REVISAO_HUMANA and r.decisao.linha_da_tabela.startswith("L2")
        assert "DUPLICATA_POSSIVEL" in {m.codigo for m in r.decisao.motivos}
        assert "DUPLICATA_POSSIVEL" in {f.codigo for f in r.fichas_conferencia}


def test_resposta_do_fallback_do_provedor_nunca_aprova_sozinha(golden, tmp_path):
    from lexis.a_domain.models import Decisao as D
    from lexis.c_extraction.config import Config
    from lexis.f_application.pipeline import Contexto
    from lexis.g_adapters.local_execution import ingerir_arquivo

    sha = ingerir_arquivo(DOCS / "02_banco_meridional_jcp.pdf").sha256
    shutil.copytree(REPLAY / sha, tmp_path / sha)
    gravacao = tmp_path / sha / "extracao.json"
    dados = json.loads(gravacao.read_text(encoding="utf-8"))
    gravacao.write_text(json.dumps({**dados, "modelo": "outro-modelo", "aviso": "respondido pelo fallback do provedor"}),
                        encoding="utf-8")
    ctx = Contexto(golden=golden, modo="replay", cfg=Config(), gravacoes=ArmazenamentoLocal(tmp_path), usar_ocr=False)
    reg = processar_documento(DOCS / "02_banco_meridional_jcp.pdf", ctx, "t")
    assert reg.decisao.estado is D.REVISAO_HUMANA
    assert "MODELO_NAO_AVALIADO" in {m.codigo for m in reg.decisao.motivos}


def test_pdf_com_outro_conteudo_nao_reaproveita_gravacao_de_mesmo_nome(ctx, tmp_path):
    outro = tmp_path / "01_energetica_vale_tiete_dividendo.pdf"
    from b_tests.conftest import criar_pdf

    criar_pdf(outro, ["AVISO AOS ACIONISTAS — Pagamento de Dividendos", "texto diferente do original"])
    r = processar_documento(outro, ctx, "t")  # mesmo nome, outro conteúdo => outro sha => sem gravação
    assert r.decisao.estado is Decisao.FALHA_PROCESSAMENTO
    assert r.decisao.motivos[0].codigo == "FIXTURE_AUSENTE"


def test_falha_nunca_e_reaproveitada_numa_nova_execucao(ctx):
    pdf = (DOCS / "02_banco_meridional_jcp.pdf").read_bytes()
    entrada = ArmazenamentoMemoria({"x.pdf": pdf})
    destino, trilha = ArmazenamentoMemoria(), TrilhaMemoria()
    sem_gravacoes = type(ctx)(golden=ctx.golden, modo="replay", cfg=ctx.cfg, gravacoes=ArmazenamentoMemoria())
    res1, _ = processar_lote(entrada, destino, trilha, sem_gravacoes)
    assert res1[0][1].decisao.estado is Decisao.FALHA_PROCESSAMENTO
    res2, _ = processar_lote(entrada, destino, trilha, ctx)  # agora há gravação: deve reprocessar, não reutilizar
    assert res2[0][2] == "PROCESSADO" and res2[0][1].decisao.estado is Decisao.APROVADO_AUTO


def test_lote_roda_inteiro_em_memoria_sem_tocar_o_disco(ctx):
    """O núcleo só depende das portas: o mesmo código serve para S3 (ver e_docs/c_architecture/aws.md)."""
    entrada = ArmazenamentoMemoria({p.name: p.read_bytes() for p in sorted(DOCS.glob("0[1-4]*.pdf"))})
    destino, trilha = ArmazenamentoMemoria(), TrilhaMemoria()
    res, run_id = processar_lote(entrada, destino, trilha, ctx)
    publicar_relatorios(destino, res, run_id)
    assert sorted(destino.listar("json/")) == [f"json/{p.stem}.json" for p in sorted(DOCS.glob("0[1-4]*.pdf"))]
    assert "relatorio_excecoes.md" in destino.listar() and trilha.eventos[0]["evento"] == "run_inicio"
    assert {r.decisao.estado for _, r, _ in res} == {Decisao.APROVADO_AUTO, Decisao.REVISAO_HUMANA, Decisao.AGUARDA_EMISSOR}
