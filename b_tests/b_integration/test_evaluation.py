import shutil

from b_tests.conftest import DOCS
from lexis.i_assessment.evaluation import avaliar_mutacoes


def test_mutacao_nao_deixa_passar_defeito_detectavel(ctx):
    rel = avaliar_mutacoes(DOCS, ctx)
    assert rel["falsos_auto_aprovados"] == [], rel["falsos_auto_aprovados"]
    assert rel["casos_detectaveis"] >= 40
    # a avaliação não é "tudo vai para revisão": há controles aprovados sem mutação, e só eles recebem defeitos
    aprovados = {c["base"] for c in rel["controles_sem_mutacao"] if c["decisao"] == "APROVADO_AUTO"}
    assert aprovados and set(rel["bases_elegiveis"]) == aprovados


def test_mutacao_cobre_todas_as_classes_e_registra_limite_conhecido(ctx):
    rel = avaliar_mutacoes(DOCS, ctx)
    assert set(rel["por_classe"]) == {"DOCUMENTO", "EXTRACAO", "INJECAO", "SCAN"}
    # honestidade: valor plausível injetado e citado no próprio documento não é detectável sem 2ª fonte
    assert any("injecao_parafraseada" in x["caso"] for x in rel["limites_conhecidos_aprovados"])


def test_mutacao_nao_depende_do_nome_nem_da_ordem_dos_arquivos(ctx, tmp_path):
    # mesmos PDFs com outros nomes (e outra ordem): as gravações são achadas pelo sha256 e os defeitos saem só do
    # conteúdo do documento e da base; se algum caso dependesse do nome do arquivo, o resultado mudaria
    for i, pdf in enumerate(sorted(DOCS.glob("*.pdf"), reverse=True)):
        shutil.copyfile(pdf, tmp_path / f"aviso_{i:03d}.pdf")
    original, renomeado = avaliar_mutacoes(DOCS, ctx), avaliar_mutacoes(tmp_path, ctx)
    assert renomeado["falsos_auto_aprovados"] == []
    for chave in ("casos_detectaveis", "detectados", "por_classe"):
        assert renomeado[chave] == original[chave], chave
