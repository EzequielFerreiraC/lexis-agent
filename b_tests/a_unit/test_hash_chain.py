"""Encadeamento de hashes da trilha: alterar, remover, reordenar ou inserir uma linha quebra a cadeia."""

import json

from lexis.a_domain.hash_chain import GENESE, calcular_hash, selar, sem_selo, verificar_cadeia
from lexis.g_adapters.local_trail import TrilhaArquivo


def _cadeia(n: int) -> list[str]:
    linhas, anterior = [], GENESE
    for i in range(n):
        selado = selar({"evento": "e", "i": i}, anterior)
        linhas.append(json.dumps(selado, ensure_ascii=False))
        anterior = selado["hash"]
    return linhas


def test_cadeia_integra_e_selo_no_fim_preservando_a_ordem():
    linhas = _cadeia(3)
    assert verificar_cadeia(linhas) == []
    primeiro = json.loads(linhas[0])
    assert list(primeiro) == ["evento", "i", "hash_anterior", "hash"] and primeiro["hash_anterior"] == GENESE
    assert sem_selo(primeiro) == {"evento": "e", "i": 0}


def test_hash_ignora_o_proprio_selo_e_depende_do_anterior():
    evento = {"evento": "e"}
    assert calcular_hash({**evento, "hash": "x", "hash_anterior": "y"}, GENESE) == calcular_hash(evento, GENESE)
    assert calcular_hash(evento, GENESE) != calcular_hash(evento, "1" * 64)


def test_alteracao_e_acusada_na_linha_alterada():
    linhas = _cadeia(3)
    linhas[1] = linhas[1].replace('"i": 1', '"i": 9')
    assert verificar_cadeia(linhas) == ["linha 2: conteúdo alterado (hash não confere)"]


def test_remocao_reordenacao_e_insercao_sao_acusadas():
    linhas = _cadeia(4)
    assert verificar_cadeia([linhas[0], linhas[2], linhas[3]])[0].startswith("linha 2: hash_anterior")
    assert verificar_cadeia([linhas[1], linhas[0], *linhas[2:]])[0].startswith("linha 1: hash_anterior")
    intrusa = json.dumps(selar({"evento": "falso"}, json.loads(linhas[0])["hash"]))
    assert any(p.startswith("linha 3: hash_anterior") for p in verificar_cadeia([linhas[0], intrusa, *linhas[1:]]))


def test_linha_sem_selo_ou_invalida_e_acusada():
    linhas = _cadeia(2)
    assert verificar_cadeia([*linhas, '{"evento": "sem selo"}']) == ["linha 3: sem selo (hash ausente)"]
    assert verificar_cadeia([linhas[0], "{quebrado"])[0] == "linha 2: não é JSON válido"


def test_trilha_em_arquivo_continua_a_cadeia_entre_instancias(tmp_path):
    arquivo = tmp_path / "auditoria.jsonl"
    TrilhaArquivo(arquivo).registrar({"evento": "lote"})
    TrilhaArquivo(arquivo).registrar({"evento": "revisao_humana"})  # outra instância, como a revisão da tela
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 2 and verificar_cadeia(linhas) == []
    assert json.loads(linhas[1])["hash_anterior"] == json.loads(linhas[0])["hash"]
