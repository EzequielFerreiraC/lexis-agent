"""API web local: segurança (token, Host, caminhos, upload), ciclo de execução, páginas, relatórios e contrato."""

import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from b_tests.conftest import DOCS, GOLDEN_CSV, REPLAY, criar_pdf
from lexis.a_domain.hash_chain import sem_selo
from lexis.c_extraction.config import Config
from lexis.f_application.integrity import verificar_integridade
from lexis.g_adapters.local_storage import ArmazenamentoLocal
from lexis.h_interfaces import contracts
from lexis.h_interfaces.api import app as modulo_app
from lexis.h_interfaces.api import security as modulo_seguranca
from lexis.h_interfaces.api import service as modulo_servico
from lexis.h_interfaces.api.app import criar_app
from lexis.h_interfaces.api.config import ConfigServidor
from lexis.h_interfaces.api.models import ExecucaoResumo
from lexis.h_interfaces.api.security import em_container, extrair_bearer, host_permitido, hostname, token_valido
from lexis.h_interfaces.api.service import ServicoExecucoes, nome_seguro
from lexis.h_interfaces.cli import main as cli_main

TOKEN = "token-de-teste-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BASE = "http://127.0.0.1:8000"


def configurar(tmp_path: Path, **extra) -> ConfigServidor:
    front = tmp_path / "front"
    (front / "assets").mkdir(parents=True, exist_ok=True)
    (front / "index.html").write_text("<!doctype html><title>lexis</title>", encoding="utf-8")
    (front / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    base = dict(token=TOKEN, raiz_amostras=DOCS, golden_csv=GOLDEN_CSV, dir_replay=REPLAY,
                dir_execucoes=tmp_path / "execucoes", dir_front=front, cfg=Config(api_key=None))
    return ConfigServidor(**{**base, **extra})


@pytest.fixture
def cliente(tmp_path):
    with TestClient(criar_app(configurar(tmp_path)), base_url=BASE) as c:
        yield c


def aguardar(cliente: TestClient, url: str, tentativas: int = 240) -> dict:
    for _ in range(tentativas):
        corpo = cliente.get(url, headers=AUTH).json()
        if corpo["estado"] in ("CONCLUIDA", "FALHOU"):
            return corpo
        time.sleep(0.25)
    raise AssertionError(f"tempo esgotado: {url}")


def executar_amostras(cliente: TestClient, **corpo) -> dict:
    r = cliente.post("/api/execucoes", headers=AUTH, json={"origem": "amostras", **corpo})
    assert r.status_code == 202, r.text
    return aguardar(cliente, f"/api/execucoes/{r.json()['id']}")


# ------------------------------------------------------------------------------------------ autenticação e host


def test_api_exige_token_em_toda_rota(cliente):
    for rota in ("/api/saude", "/api/catalogo", "/api/amostras", "/api/execucoes", "/api/nada"):
        assert cliente.get(rota).status_code == 401, rota
    assert cliente.get("/api/saude", headers={"Authorization": "Bearer errado"}).status_code == 401
    assert cliente.get("/api/saude", headers={"Authorization": f"Basic {TOKEN}"}).status_code == 401
    assert cliente.post("/api/execucoes", json={"origem": "amostras"}).status_code == 401
    assert cliente.get("/api/saude", headers=AUTH).status_code == 200


def test_token_nao_aceito_por_query_string(cliente):
    assert cliente.get(f"/api/saude?token={TOKEN}").status_code == 401


def test_upload_sem_token_e_recusado_antes_de_ler_o_corpo(cliente):
    r = cliente.post("/api/uploads", files={"arquivos": ("a.pdf", b"%PDF-" + b"0" * 1000)})
    assert r.status_code == 401


def test_host_estranho_e_recusado_dns_rebinding(cliente):
    assert cliente.get("/api/saude", headers={**AUTH, "Host": "atacante.example"}).status_code == 400
    assert cliente.get("/api/saude", headers={**AUTH, "Host": "127.0.0.1.atacante.example"}).status_code == 400
    assert cliente.get("/", headers={"Host": "atacante.example"}).status_code == 400
    for ok in ("127.0.0.1:8000", "localhost:5173", "[::1]:8000", "localhost"):
        assert cliente.get("/api/saude", headers={**AUTH, "Host": ok}).status_code == 200, ok


def test_funcoes_de_seguranca():
    assert hostname("[::1]:8000") == "[::1]" and hostname("Localhost:3000") == "localhost"
    assert host_permitido("127.0.0.1:1") and not host_permitido("0.0.0.0:1") and not host_permitido(None)
    assert extrair_bearer("Bearer abc") == "abc" and extrair_bearer("bearer  abc ") == "abc"
    assert extrair_bearer("Basic abc") is None and extrair_bearer(None) is None
    assert token_valido("x", "x") and not token_valido("x", "y") and not token_valido(None, "y")


def test_cabecalhos_de_seguranca_e_sem_cache_na_api(cliente):
    r = cliente.get("/api/saude", headers=AUTH)
    assert "default-src 'none'" in r.headers["content-security-policy"] and "unsafe-inline" not in r.headers[
        "content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"
    assert "content-security-policy" in cliente.get("/").headers  # também no front


def test_serve_recusa_host_que_nao_e_loopback(capsys):
    assert cli_main(["serve", "--host", "0.0.0.0"]) == 2  # noqa: S104
    assert "loopback" in capsys.readouterr().err


def test_serve_container_so_vale_dentro_de_um_container(capsys, monkeypatch):
    monkeypatch.setattr(modulo_seguranca, "em_container", lambda: False)
    assert cli_main(["serve", "--container"]) == 2
    assert "dentro de um container" in capsys.readouterr().err


def test_serve_container_escuta_na_interface_do_container_e_mostra_loopback(capsys, monkeypatch, tmp_path):
    chamadas: dict[str, object] = {}
    monkeypatch.setattr(modulo_seguranca, "em_container", lambda: True)
    monkeypatch.setattr("uvicorn.run", lambda _app, **kw: chamadas.update(kw))
    monkeypatch.setenv("LEXIS_TOKEN", TOKEN)
    assert cli_main(["serve", "--container", "--porta", "8123", "--execucoes", str(tmp_path)]) == 0
    assert chamadas["host"] == "0.0.0.0" and chamadas["port"] == 8123  # noqa: S104
    # o endereço impresso é o do host (porta publicada em 127.0.0.1), nunca 0.0.0.0
    assert f"http://127.0.0.1:8123/#token={TOKEN}" in capsys.readouterr().out


def test_em_container_depende_dos_marcadores(tmp_path):
    marcador = tmp_path / ".dockerenv"
    assert not em_container((marcador,))
    marcador.touch()
    assert em_container((marcador,))


# ------------------------------------------------------------------------------------------ catálogo e amostras


def test_saude_catalogo_e_amostras(cliente):
    s = cliente.get("/api/saude", headers=AUTH).json()
    modos = {m["id"]: m for m in s["modos"]}
    assert modos["replay"]["disponivel"] and not modos["live"]["disponivel"]  # sem chave no servidor
    assert "ANTHROPIC_API_KEY" in modos["live"]["motivo_indisponivel"]
    assert s["gravacoes_simuladas"] is False and s["limites"]["max_arquivos"] == 20  # c_replay/ = respostas reais
    assert not any("sk-" in json.dumps(s) for _ in [0])  # nenhuma chave no corpo
    c = cliente.get("/api/catalogo", headers=AUTH).json()
    assert c["rotulos"]["valor_bruto"] == "Valor bruto por ação" and "JCP" in c["tipos"]
    assert c["regras"]["TITULO_DIVERGE_CORPO"]["severidade"] == "AVISO"
    nomes = [a["nome"] for a in cliente.get("/api/amostras", headers=AUTH).json()]
    assert len(nomes) == 8 and nomes[0].startswith("01_")


# ------------------------------------------------------------------------------------------ execução (replay)


def test_execucao_replay_das_amostras_reproduz_a_cli(cliente):
    antes = sorted(p.relative_to(REPLAY).as_posix() for p in REPLAY.rglob("*") if p.is_file())
    r = executar_amostras(cliente)
    assert r["estado"] == "CONCLUIDA" and r["total"] == r["concluidos"] == 8
    assert r["contagem"] == {"APROVADO_AUTO": 4, "AGUARDA_EMISSOR": 1, "REVISAO_HUMANA": 3, "FALHA_PROCESSAMENTO": 0}
    por = {d["arquivo"]: d for d in r["documentos"]}
    assert por["03_siderurgica_paranaense_proventos.pdf"]["motivos"] == ["TITULO_DIVERGE_CORPO"]
    assert por["04_rede_varejo_jcp_sem_data.pdf"]["estado"] == "AGUARDA_EMISSOR"
    assert por["08_construtora_horizonte_bonificacao.pdf"]["golden"] == "NOT_FOUND"
    assert por["07_telecom_norte_jcp_SCAN.pdf"]["fonte"] == "SCAN"
    assert por["07_telecom_norte_jcp_SCAN.pdf"]["estado"] == "APROVADO_AUTO"  # OCR gravado corrobora
    assert r["extracoes_simuladas"] is False and r["versoes"]["schema"] == "1.1"
    depois = sorted(p.relative_to(REPLAY).as_posix() for p in REPLAY.rglob("*") if p.is_file())
    assert antes == depois, "a interface nunca pode alterar as gravações versionadas"


def test_sem_ocr_o_scan_volta_para_revisao_humana(cliente):
    r = executar_amostras(cliente, arquivos=["07_telecom_norte_jcp_SCAN.pdf"], sem_ocr=True)
    doc = r["documentos"][0]
    assert doc["estado"] == "REVISAO_HUMANA" and doc["motivos"] == ["OCR_INDISPONIVEL"]


def test_documento_detalhe_e_relatorios(cliente):
    r = executar_amostras(cliente, arquivos=["05_aurora_saneamento_dividendo_datas.pdf"])
    base = f"/api/execucoes/{r['id']}"
    reg = cliente.get(f"{base}/documentos/05_aurora_saneamento_dividendo_datas.pdf", headers=AUTH).json()
    assert reg["decisao"]["estado"] == "REVISAO_HUMANA" and reg["schema_version"] == "1.1"
    assert reg["campos"]["data_pagamento"]["evidencia"]["bbox"] is not None
    md = cliente.get(f"{base}/relatorios/relatorio_excecoes.md", headers=AUTH)
    assert md.status_code == 200 and "05_aurora" in md.text and "attachment" in md.headers["content-disposition"]
    assert cliente.get(f"{base}/relatorios/auditoria.jsonl", headers=AUTH).status_code == 200
    assert cliente.get(f"{base}/relatorios/resumo_execucao.json", headers=AUTH).json()["run_id"]


def test_pagina_e_imagem_da_pagina(cliente):
    r = executar_amostras(cliente, arquivos=["01_energetica_vale_tiete_dividendo.pdf"])
    url = f"/api/execucoes/{r['id']}/documentos/01_energetica_vale_tiete_dividendo.pdf/paginas/1"
    meta = cliente.get(url, headers=AUTH).json()
    assert meta["total_paginas"] == 1 and 500 < meta["largura_pt"] < 700 and 700 < meta["altura_pt"] < 900
    img = cliente.get(url + "/imagem", headers=AUTH)
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert cliente.get(url.replace("/paginas/1", "/paginas/2"), headers=AUTH).status_code == 404
    assert cliente.get(url.replace("/paginas/1", "/paginas/0"), headers=AUTH).status_code == 404


def test_scan_tem_imagem_mas_sem_bbox(cliente):
    r = executar_amostras(cliente, arquivos=["07_telecom_norte_jcp_SCAN.pdf"])
    base = f"/api/execucoes/{r['id']}/documentos/07_telecom_norte_jcp_SCAN.pdf"
    assert cliente.get(f"{base}/paginas/1/imagem", headers=AUTH).status_code == 200
    reg = cliente.get(base, headers=AUTH).json()
    assert all(c["evidencia"] is None or c["evidencia"]["bbox"] is None for c in reg["campos"].values())


def test_listagem_e_progresso(cliente):
    r = executar_amostras(cliente, arquivos=["02_banco_meridional_jcp.pdf"])
    pagina = cliente.get("/api/execucoes", headers=AUTH).json()
    itens = pagina["itens"]
    assert itens[0]["id"] == r["id"] and itens[0]["total"] == 1 and "documentos" not in itens[0]
    assert pagina["total"] == 1 and pagina["limite"] == 20 and pagina["deslocamento"] == 0


def _semear_execucoes(pasta: Path, quantas: int) -> list[str]:
    """Grava execuções concluídas no disco, como o servidor faria, com horários distintos (a mais nova por último)."""
    ids = []
    for i in range(quantas):
        run_id = f"{i:012x}"
        (pasta / run_id).mkdir(parents=True)
        resumo = ExecucaoResumo(id=run_id, criada_em=f"2026-10-01T10:{i:02d}:00+00:00", estado="CONCLUIDA",
                                modo="replay", origem="upload", total=1, concluidos=1, contagem={}, sem_ocr=False)
        (pasta / run_id / "execucao.json").write_text(resumo.model_dump_json(), encoding="utf-8")
        ids.append(run_id)
    return ids


def test_listagem_paginada_cobre_todas_sem_repetir(tmp_path):
    ids = _semear_execucoes(tmp_path / "execucoes", 25)
    with TestClient(criar_app(configurar(tmp_path)), base_url=BASE) as c:
        vistos: list[str] = []
        for deslocamento in (0, 10, 20):
            pagina = c.get(f"/api/execucoes?limite=10&deslocamento={deslocamento}", headers=AUTH).json()
            assert pagina["total"] == 25 and pagina["limite"] == 10 and pagina["deslocamento"] == deslocamento
            vistos += [i["id"] for i in pagina["itens"]]
        assert vistos == list(reversed(ids)), "mais recentes primeiro, sem buracos nem repetição"
        fim = c.get("/api/execucoes?limite=10&deslocamento=30", headers=AUTH).json()
        assert fim["itens"] == [] and fim["total"] == 25  # além do fim: página vazia, não erro


@pytest.mark.parametrize("consulta", ["limite=0", "limite=101", "limite=abc", "deslocamento=-1"])
def test_listagem_recusa_paginacao_invalida(cliente, consulta):
    assert cliente.get(f"/api/execucoes?{consulta}", headers=AUTH).status_code == 422


# ------------------------------------------------------------------------------------------ caminhos e entradas


@pytest.mark.parametrize("ruim", ["../../etc/passwd", "/etc/passwd", "..\\..\\x.pdf", "inexistente.pdf", ""])
def test_nomes_de_arquivo_nunca_viram_caminho(cliente, ruim):
    r = cliente.post("/api/execucoes", headers=AUTH, json={"origem": "amostras", "arquivos": [ruim]})
    assert r.status_code == 400


def test_ids_e_nomes_invalidos_dao_404(cliente):
    for url in ("/api/execucoes/..%2f..%2fx", "/api/execucoes/zzzzzzzzzzzz", "/api/execucoes/ABCDEF123456",
                "/api/execucoes/000000000000/relatorios/relatorio_excecoes.md"):
        assert cliente.get(url, headers=AUTH).status_code == 404, url
    r = executar_amostras(cliente, arquivos=["02_banco_meridional_jcp.pdf"])
    base = f"/api/execucoes/{r['id']}"
    for ruim in ("..%2f..%2fpyproject.toml", "03_siderurgica_paranaense_proventos.pdf", "x"):
        assert cliente.get(f"{base}/documentos/{ruim}", headers=AUTH).status_code == 404, ruim
    for arq in ("../../pyproject.toml", "execucao.json", "json/02_banco_meridional_jcp.json"):
        assert cliente.get(f"{base}/relatorios/{arq}", headers=AUTH).status_code == 404, arq


def test_corpo_da_execucao_e_estrito(cliente):
    assert cliente.post("/api/execucoes", headers=AUTH, json={"origem": "amostras", "caminho": "/tmp"}).status_code == 422
    assert cliente.post("/api/execucoes", headers=AUTH, json={"origem": "disco"}).status_code == 422
    assert cliente.post("/api/execucoes", headers=AUTH,
                        json={"origem": "upload", "upload_id": "../../x"}).status_code == 422


def test_nome_seguro():
    assert nome_seguro("../../etc/passwd") == "passwd.pdf"
    assert nome_seguro("C:\\temp\\Aviso 1.PDF") == "Aviso 1.pdf"
    assert nome_seguro("a<b>|c?.pdf") == "a_b__c_.pdf"
    assert nome_seguro("...") == "documento.pdf" and nome_seguro("") == "documento.pdf"
    assert nome_seguro("x.pdf", {"x.pdf"}) == "x_2.pdf"
    assert len(nome_seguro("a" * 500)) <= 100


# ------------------------------------------------------------------------------------------ upload


def test_upload_de_amostra_conhecida_reaproveita_gravacao_por_sha(cliente):
    pdf = (DOCS / "02_banco_meridional_jcp.pdf").read_bytes()
    up = cliente.post("/api/uploads", headers=AUTH, files=[("arquivos", ("../../meu aviso.pdf", pdf))])
    assert up.status_code == 201 and up.json()["arquivos"][0]["nome"] == "meu aviso.pdf"
    r = cliente.post("/api/execucoes", headers=AUTH, json={"origem": "upload", "upload_id": up.json()["id"]})
    assert r.status_code == 202
    fim = aguardar(cliente, f"/api/execucoes/{r.json()['id']}")
    assert fim["documentos"][0]["estado"] == "APROVADO_AUTO"  # o conteúdo é o mesmo: a gravação é achada pelo sha


def test_upload_de_pdf_novo_em_replay_falha_de_forma_explicita(cliente, tmp_path):
    novo = criar_pdf(tmp_path / "novo.pdf", ["AVISO AOS ACIONISTAS", "texto qualquer sem gravação"])
    up = cliente.post("/api/uploads", headers=AUTH, files={"arquivos": ("novo.pdf", novo.read_bytes())})
    r = cliente.post("/api/execucoes", headers=AUTH, json={"origem": "upload", "upload_id": up.json()["id"]})
    doc = aguardar(cliente, f"/api/execucoes/{r.json()['id']}")["documentos"][0]
    assert doc["estado"] == "FALHA_PROCESSAMENTO" and doc["motivos"] == ["FIXTURE_AUSENTE"]


def test_upload_rejeita_o_que_nao_e_pdf_e_o_que_e_grande(cliente, monkeypatch):
    r = cliente.post("/api/uploads", headers=AUTH, files={"arquivos": ("a.pdf", b"MZ\x90 nao e pdf")})
    assert r.status_code == 415
    monkeypatch.setattr(modulo_servico, "MAX_BYTES", 50)
    monkeypatch.setattr(modulo_app, "MAX_BYTES", 50)
    r = cliente.post("/api/uploads", headers=AUTH, files={"arquivos": ("a.pdf", b"%PDF-" + b"0" * 200)})
    assert r.status_code == 413


def test_upload_limita_a_quantidade_de_arquivos(tmp_path):
    with TestClient(criar_app(configurar(tmp_path, max_arquivos=2)), base_url=BASE) as c:
        pdf = b"%PDF-1.4 x"
        r = c.post("/api/uploads", headers=AUTH, files=[("arquivos", (f"{i}.pdf", pdf)) for i in range(3)])
        assert r.status_code == 413


def test_upload_sem_content_length_e_recusado(cliente):
    def corpo():
        yield b"--x\r\n"

    r = cliente.post("/api/uploads", headers={**AUTH, "Content-Type": "multipart/form-data; boundary=x"},
                     content=corpo())
    assert r.status_code == 413


# ------------------------------------------------------------------------------------------ modo live


def test_live_sem_chave_e_recusado_e_com_chave_exige_confirmacao(tmp_path):
    with TestClient(criar_app(configurar(tmp_path)), base_url=BASE) as sem_chave:
        r = sem_chave.post("/api/execucoes", headers=AUTH, json={"origem": "amostras", "modo": "live",
                                                                  "confirmar_live": True})
        assert r.status_code == 400 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    with TestClient(criar_app(configurar(tmp_path, cfg=Config(api_key="chave-falsa"))), base_url=BASE) as com_chave:
        saude = com_chave.get("/api/saude", headers=AUTH).text
        assert "chave-falsa" not in saude  # a chave nunca chega ao navegador
        r = com_chave.post("/api/execucoes", headers=AUTH, json={"origem": "amostras", "modo": "live"})
        assert r.status_code == 400 and "confirme" in r.json()["detail"]
        assert not list((tmp_path / "execucoes").glob("[0-9a-f]" * 12)), "nada pode ter sido criado sem confirmação"


# ------------------------------------------------------------------------------------------ modelo e chave (configuração)

CHAVE_TELA = "sk-ant-api03-" + "x" * 40 + "WXYZ"
CHAVE_AMBIENTE = "sk-ant-api03-" + "a" * 40 + "ENV1"


def test_configuracao_exige_token(cliente):
    for metodo, rota in (("get", "/api/configuracao"), ("put", "/api/configuracao/chave"),
                         ("delete", "/api/configuracao/chave")):
        assert getattr(cliente, metodo)(rota).status_code == 401, (metodo, rota)


def test_configuracao_mostra_o_modelo_do_ambiente_com_preco(cliente):
    c = cliente.get("/api/configuracao", headers=AUTH).json()
    assert (c["provedor"], c["modelo"]) == ("Anthropic", "claude-sonnet-5-5")
    assert c["preco_entrada_usd_mtok"] is not None and c["preco_saida_usd_mtok"] is not None
    assert c["chave"] == {"configurada": False, "origem": None, "final": None}


def test_modelo_nao_se_troca_pela_api(cliente):
    # Só o modelo avaliado (gravações + mutação) roda; trocar é configuração de deploy (LEXIS_MODEL), não do operador.
    r = cliente.put("/api/configuracao/modelo", headers=AUTH, json={"provedor": "anthropic", "nivel": "forte"})
    assert r.status_code in (404, 405)
    assert cliente.get("/api/saude", headers=AUTH).json()["modelo"] == "claude-sonnet-5-5"


def test_modelo_fora_da_tabela_de_precos_nao_ganha_preco_inventado(tmp_path):
    cfg = Config(modelo="modelo-interno-x", api_key=None)
    with TestClient(criar_app(configurar(tmp_path, cfg=cfg)), base_url=BASE) as c:
        conf = c.get("/api/configuracao", headers=AUTH).json()
        assert conf["modelo"] == "modelo-interno-x"
        assert (conf["preco_entrada_usd_mtok"], conf["preco_saida_usd_mtok"]) == (None, None)


def _live_disponivel(cliente) -> bool:
    modos = cliente.get("/api/saude", headers=AUTH).json()["modos"]
    return next(m for m in modos if m["id"] == "live")["disponivel"]


def test_chave_digitada_liga_o_modo_live_sem_nunca_voltar_inteira(cliente):
    assert not _live_disponivel(cliente)
    r = cliente.put("/api/configuracao/chave", headers=AUTH, json={"chave": f"  {CHAVE_TELA}  "})
    assert r.status_code == 200
    assert r.json()["chave"] == {"configurada": True, "origem": "tela", "final": "WXYZ"}
    for rota in ("/api/configuracao", "/api/saude"):
        corpo = cliente.get(rota, headers=AUTH).text
        assert CHAVE_TELA not in corpo and "x" * 20 not in corpo, rota
    assert _live_disponivel(cliente)
    voltou = cliente.delete("/api/configuracao/chave", headers=AUTH).json()
    assert voltou["chave"] == {"configurada": False, "origem": None, "final": None}
    assert not _live_disponivel(cliente)


@pytest.mark.parametrize("ruim", ["", "   ", "chave-qualquer", "sk-ant-curta", "sk-ant-" + "a" * 30 + " b" * 3,
                                  "sk-ant-" + "a" * 30 + "\nX-Injetado: 1", "sk-ant-" + "é" * 30])
def test_chave_com_formato_invalido_e_recusada_sem_ecoar_o_que_foi_digitado(cliente, ruim):
    r = cliente.put("/api/configuracao/chave", headers=AUTH, json={"chave": ruim})
    assert r.status_code == 400
    assert not ruim.strip() or ruim.strip() not in r.text
    assert cliente.get("/api/configuracao", headers=AUTH).json()["chave"]["configurada"] is False


def test_chave_enorme_e_recusada_antes_de_virar_segredo(cliente):
    r = cliente.put("/api/configuracao/chave", headers=AUTH, json={"chave": "sk-ant-" + "a" * 600})
    assert r.status_code == 400
    assert "a" * 100 not in r.text  # o 422 padrão do FastAPI ecoaria a entrada; por isso o limite é conferido no serviço
    assert cliente.get("/api/configuracao", headers=AUTH).json()["chave"]["configurada"] is False


def test_chave_da_tela_vence_a_do_ambiente_e_remover_volta_para_ela(tmp_path):
    with TestClient(criar_app(configurar(tmp_path, cfg=Config(api_key=CHAVE_AMBIENTE))), base_url=BASE) as c:
        assert c.get("/api/configuracao", headers=AUTH).json()["chave"] == {
            "configurada": True, "origem": "ambiente", "final": "ENV1"}
        assert c.put("/api/configuracao/chave", headers=AUTH, json={"chave": CHAVE_TELA}).json()["chave"][
            "origem"] == "tela"
        assert c.delete("/api/configuracao/chave", headers=AUTH).json()["chave"]["origem"] == "ambiente"


def test_chave_fica_so_em_memoria_e_fora_do_repr(tmp_path):
    cfg = Config(api_key=CHAVE_AMBIENTE)
    assert CHAVE_AMBIENTE not in repr(cfg) and "ENV1" not in repr(cfg)
    config = configurar(tmp_path)
    with TestClient(criar_app(config), base_url=BASE) as c:
        c.put("/api/configuracao/chave", headers=AUTH, json={"chave": CHAVE_TELA})
        executar_amostras(c)  # replay: não usa a chave, mas passa por todo o caminho de gravação
    for arq in (tmp_path / "execucoes").rglob("*"):
        if arq.is_file():
            assert CHAVE_TELA.encode() not in arq.read_bytes(), f"chave gravada em {arq}"
    with TestClient(criar_app(config), base_url=BASE) as reiniciado:  # novo processo: a escolha da tela some
        assert reiniciado.get("/api/configuracao", headers=AUTH).json()["chave"]["configurada"] is False


def test_custo_do_haiku_usa_a_tabela_de_precos():
    from lexis.c_extraction.costs import estimar_custo_usd

    assert estimar_custo_usd("claude-haiku-5-5", 1_000_000, 1_000_000) == 0.6


# ------------------------------------------------------------------------------------------ front estático


def test_front_estatico_e_spa_fallback(cliente):
    assert "<title>lexis</title>" in cliente.get("/").text
    assert "<title>lexis</title>" in cliente.get("/execucoes/abc123/documentos/x").text  # rota do React Router
    js = cliente.get("/assets/app.js")
    assert js.text == "console.log(1)" and "immutable" in js.headers["cache-control"]
    assert cliente.get("/").headers["cache-control"] == "no-cache"


def test_front_nao_serve_arquivos_fora_da_pasta_do_build(cliente):
    for tentativa in ("/%2e%2e/%2e%2e/pyproject.toml", "/..%2f..%2fpyproject.toml", "/assets/..%2f..%2f..%2fpyproject.toml"):
        r = cliente.get(tentativa)
        assert "[project]" not in r.text and "lexis" in r.text, tentativa  # cai no index, nunca no arquivo real


def test_front_nao_compilado_avisa_com_clareza(tmp_path):
    cfg = configurar(tmp_path, dir_front=tmp_path / "inexistente")
    with TestClient(criar_app(cfg), base_url=BASE) as c:
        r = c.get("/")
        assert r.status_code == 503 and "npm run build" in r.json()["detail"]
        assert c.get("/api/rota-inexistente", headers=AUTH).status_code == 404


# ------------------------------------------------------------------------------------------ persistência e contrato


def test_execucao_interrompida_por_reinicio_vira_falha(tmp_path):
    cfg = configurar(tmp_path)
    pasta = cfg.dir_execucoes / "abcdef012345"
    pasta.mkdir(parents=True)
    (pasta / "execucao.json").write_text(json.dumps({
        "id": "abcdef012345", "criada_em": "2026-01-01T00:00:00+00:00", "estado": "EM_ANDAMENTO", "modo": "replay",
        "origem": "amostras", "total": 3, "concluidos": 1, "contagem": {}, "sem_ocr": False}), encoding="utf-8")
    (pasta / "execucao_invalida.json").write_text("{", encoding="utf-8")
    svc = ServicoExecucoes(cfg)
    try:
        r = svc.obter_execucao("abcdef012345")
        assert r.estado == "FALHOU" and "reiniciado" in (r.erro or "")
    finally:
        svc.encerrar()


# ------------------------------------------------------------------------------------------ revisão humana

DOC_05 = "05_aurora_saneamento_dividendo_datas.pdf"


def _revisar(cliente: TestClient, run_id: str, nome: str = DOC_05, **corpo):
    padrao = {"decisao": "APROVADO_NA_REVISAO", "operador": "Operadora A", "justificativa": "Conferido contra o aviso."}
    return cliente.post(f"/api/execucoes/{run_id}/documentos/{nome}/revisao", headers=AUTH, json={**padrao, **corpo})


def _motivos(cliente: TestClient, run_id: str, nome: str = DOC_05) -> list[str]:
    reg = cliente.get(f"/api/execucoes/{run_id}/documentos/{nome}", headers=AUTH).json()
    return sorted({m["codigo"] for m in reg["decisao"]["motivos"]})


def test_aprovar_na_revisao_grava_ao_lado_sem_alterar_o_registro(cliente, tmp_path):
    r = executar_amostras(cliente, arquivos=[DOC_05])
    saida = tmp_path / "execucoes" / r["id"] / "saida"
    arquivo_registro = next(saida.glob("json/*.json"))
    antes = arquivo_registro.read_bytes()
    motivos = _motivos(cliente, r["id"])
    assert motivos, "o doc 05 precisa ter motivos de revisão"

    resp = _revisar(cliente, r["id"], operador="  Operadora   A ", motivos_reconhecidos=motivos)
    assert resp.status_code == 201, resp.text
    rev = resp.json()
    assert rev["decisao"] == "APROVADO_NA_REVISAO" and rev["decisao_automatica"] == "REVISAO_HUMANA"
    assert rev["operador"] == "Operadora A" and rev["motivos_reconhecidos"] == motivos
    assert rev["sha256_registro"] == hashlib.sha256(antes).hexdigest()

    assert arquivo_registro.read_bytes() == antes, "a decisão humana nunca altera o registro do pipeline"
    reg = cliente.get(f"/api/execucoes/{r['id']}/documentos/{DOC_05}", headers=AUTH).json()
    assert reg["decisao"]["estado"] == "REVISAO_HUMANA"
    doc = cliente.get(f"/api/execucoes/{r['id']}", headers=AUTH).json()["documentos"][0]
    assert doc["estado"] == "REVISAO_HUMANA" and doc["revisao"]["decisao"] == "APROVADO_NA_REVISAO"

    linha = json.loads((saida / "revisoes.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert linha["arquivo"] == DOC_05 and linha["justificativa"] == "Conferido contra o aviso."
    evento = json.loads((saida / "auditoria.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert evento["evento"] == "revisao_humana" and evento["decisao"] == "APROVADO_NA_REVISAO"
    # a trilha só leva códigos e hashes: nem o nome do operador nem a justificativa
    assert "Operadora" not in json.dumps(evento) and "Conferido" not in json.dumps(evento)
    sha_linha = hashlib.sha256(json.dumps(sem_selo(linha), ensure_ascii=False).encode()).hexdigest()  # sem o selo
    assert evento["sha256_revisao"] == sha_linha


def test_decisao_do_operador_entra_na_verificacao_de_integridade(cliente, tmp_path):
    r = executar_amostras(cliente, arquivos=[DOC_05])
    assert _revisar(cliente, r["id"], motivos_reconhecidos=_motivos(cliente, r["id"])).status_code == 201
    saida = tmp_path / "execucoes" / r["id"] / "saida"
    assert all(v.ok for v in verificar_integridade(ArmazenamentoLocal(saida)))

    revisoes = saida / "revisoes.jsonl"
    revisoes.write_text(revisoes.read_text(encoding="utf-8").replace("Conferido contra o aviso.", "Outro motivo."),
                        encoding="utf-8")
    problemas = {v.nome: v.problemas for v in verificar_integridade(ArmazenamentoLocal(saida))}
    assert any("conteúdo alterado" in p for p in problemas["Decisões do operador"])
    assert any("sem o evento revisao_humana" in p for p in problemas["Decisões do operador"])
    revisoes.unlink()
    problemas = {v.nome: v.problemas for v in verificar_integridade(ArmazenamentoLocal(saida))}
    assert any("revisoes.jsonl não existe" in p for p in problemas["Decisões do operador"])


def test_aprovar_exige_reconhecer_todos_os_motivos_e_rejeitar_nao(cliente):
    r = executar_amostras(cliente, arquivos=[DOC_05])
    motivos = _motivos(cliente, r["id"])
    resp = _revisar(cliente, r["id"], motivos_reconhecidos=motivos[:-1])
    assert resp.status_code == 400 and "todos os motivos" in resp.json()["detail"]
    resp = _revisar(cliente, r["id"], motivos_reconhecidos=[*motivos, "INVENTADO"])
    assert resp.status_code == 400 and "não pertence" in resp.json()["detail"]
    resp = _revisar(cliente, r["id"], decisao="REJEITADO_NA_REVISAO", justificativa="Data de pagamento errada.")
    assert resp.status_code == 201 and resp.json()["motivos_reconhecidos"] == []


def test_uma_decisao_por_documento_e_ela_sobrevive_ao_reinicio(tmp_path):
    cfg = configurar(tmp_path)
    with TestClient(criar_app(cfg), base_url=BASE) as cliente:
        r = executar_amostras(cliente, arquivos=[DOC_05])
        assert _revisar(cliente, r["id"], motivos_reconhecidos=_motivos(cliente, r["id"])).status_code == 201
        segunda = _revisar(cliente, r["id"], decisao="REJEITADO_NA_REVISAO")
        assert segunda.status_code == 409 and "já foi revisado" in segunda.json()["detail"]
    svc = ServicoExecucoes(cfg)
    try:
        doc = svc.obter_execucao(r["id"]).documentos[0]
        assert doc.revisao is not None and doc.revisao.decisao == "APROVADO_NA_REVISAO"
    finally:
        svc.encerrar()


def test_revisao_so_vale_para_documento_em_revisao_humana_e_com_entrada_valida(cliente):
    r = executar_amostras(cliente, arquivos=["02_banco_meridional_jcp.pdf", "04_rede_varejo_jcp_sem_data.pdf", DOC_05])
    for nome in ("02_banco_meridional_jcp.pdf", "04_rede_varejo_jcp_sem_data.pdf"):  # aprovado / aguarda emissor
        resp = _revisar(cliente, r["id"], nome, decisao="REJEITADO_NA_REVISAO")
        assert resp.status_code == 400 and "revisão humana" in resp.json()["detail"], nome
    assert _revisar(cliente, r["id"], operador=" ", decisao="REJEITADO_NA_REVISAO").status_code == 400
    assert _revisar(cliente, r["id"], justificativa=" curta ", decisao="REJEITADO_NA_REVISAO").status_code == 400
    assert _revisar(cliente, r["id"], decisao="APROVADO_AUTO").status_code == 422
    assert _revisar(cliente, r["id"], decisao="REJEITADO_NA_REVISAO", estado="APROVADO_AUTO").status_code == 422
    assert _revisar(cliente, r["id"], "inexistente.pdf", decisao="REJEITADO_NA_REVISAO").status_code == 404
    # com barras o caminho nem casa com a rota de revisão (cai no front, que só aceita GET): nada chega ao serviço
    assert _revisar(cliente, r["id"], "..%2f..%2fpyproject.toml", decisao="REJEITADO_NA_REVISAO").status_code in (404,
                                                                                                                  405)
    assert _revisar(cliente, "000000000000", decisao="REJEITADO_NA_REVISAO").status_code == 404
    url = f"/api/execucoes/{r['id']}/documentos/{DOC_05}/revisao"
    assert cliente.post(url, json={"decisao": "REJEITADO_NA_REVISAO"}).status_code == 401


def test_contrato_openapi_publicado_acompanha_o_codigo():
    assert contracts.DESTINO_OPENAPI.read_text(encoding="utf-8") == contracts.openapi_atual(), (
        "contrato mudou: rode `lexis contratos` e `npm run gen:api` em a_src/a_frontend")
