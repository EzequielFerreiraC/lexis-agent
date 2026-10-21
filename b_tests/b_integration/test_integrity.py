"""`lexis auditar`: a execução é a que foi gravada? Trilha, registros e decisões do operador."""

import json
import shutil

from b_tests.conftest import DOCS
from lexis.f_application.integrity import verificar_integridade
from lexis.g_adapters.local_execution import executar_lote
from lexis.g_adapters.local_storage import ArmazenamentoLocal
from lexis.h_interfaces.cli import main as cli_main


def _executar(ctx, tmp_path, *nomes):
    entrada = tmp_path / "in"
    entrada.mkdir()
    for nome in nomes:
        shutil.copy(DOCS / nome, entrada)
    saida = tmp_path / "out"
    executar_lote(entrada, saida, ctx)
    return saida


def _problemas(saida) -> dict[str, list[str]]:
    return {v.nome: v.problemas for v in verificar_integridade(ArmazenamentoLocal(saida))}


def test_execucao_recem_gravada_e_integra_e_sela_cada_registro(ctx, tmp_path):
    saida = _executar(ctx, tmp_path, "01_energetica_vale_tiete_dividendo.pdf", "05_aurora_saneamento_dividendo_datas.pdf")
    assert all(not p for p in _problemas(saida).values())
    eventos = [json.loads(x) for x in (saida / "auditoria.jsonl").read_text(encoding="utf-8").splitlines()]
    selo = next(e for e in eventos if e["evento"] == "registros_publicados")
    assert set(selo["registros"]) == {"json/01_energetica_vale_tiete_dividendo.json",
                                      "json/05_aurora_saneamento_dividendo_datas.json"}
    assert all("hash" in e and "hash_anterior" in e for e in eventos)


def test_registro_alterado_removido_ou_acrescentado_e_acusado(ctx, tmp_path):
    saida = _executar(ctx, tmp_path, "01_energetica_vale_tiete_dividendo.pdf", "02_banco_meridional_jcp.pdf")
    registro = saida / "json" / "01_energetica_vale_tiete_dividendo.json"
    registro.write_text(registro.read_text(encoding="utf-8").replace("APROVADO_AUTO", "REVISAO_HUMANA"), encoding="utf-8")
    (saida / "json" / "02_banco_meridional_jcp.json").unlink()
    (saida / "json" / "99_intruso.json").write_text("{}", encoding="utf-8")
    problemas = _problemas(saida)["Registros contra o selo da trilha"]
    assert any("01_energetica" in p and "alterado" in p for p in problemas)
    assert any("02_banco" in p and "ausente" in p for p in problemas)
    assert any("99_intruso" in p and "não consta" in p for p in problemas)


def test_trilha_editada_e_acusada_mesmo_que_o_registro_esteja_intacto(ctx, tmp_path):
    saida = _executar(ctx, tmp_path, "05_aurora_saneamento_dividendo_datas.pdf")
    trilha = saida / "auditoria.jsonl"
    trilha.write_text(trilha.read_text(encoding="utf-8").replace('"REVISAO_HUMANA"', '"APROVADO_AUTO"', 1),
                      encoding="utf-8")
    assert _problemas(saida)["Cadeia da trilha"] == ["linha 2: conteúdo alterado (hash não confere)"]


def test_cli_auditar_devolve_0_se_integra_e_1_se_nao(ctx, tmp_path, capsys):
    saida = _executar(ctx, tmp_path, "02_banco_meridional_jcp.pdf")
    assert cli_main(["auditar", str(saida)]) == 0 and "Íntegra" in capsys.readouterr().out
    (saida / "auditoria.jsonl").write_text("", encoding="utf-8")
    assert cli_main(["auditar", str(saida)]) == 1 and "NÃO íntegra" in capsys.readouterr().out
    assert cli_main(["auditar", str(tmp_path / "nao_existe")]) == 2
