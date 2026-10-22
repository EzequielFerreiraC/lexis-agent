"""Login do console (só com banco) e projeção das execuções e revisões no banco, pela API."""


import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from b_tests.b_integration.test_api import AUTH, BASE, DOC_05, _motivos, _revisar, configurar, executar_amostras
from lexis.g_adapters.sql_schema import documento, revisao, usuario
from lexis.g_adapters.sql_store import conectar
from lexis.g_adapters.sql_users import criar_usuario
from lexis.h_interfaces.api import service as modulo_servico
from lexis.h_interfaces.api.app import COOKIE_SESSAO, criar_app
from lexis.h_interfaces.api.config import dominios_do_ambiente

SENHA = "senha-do-operador-longa"


@pytest.fixture
def com_banco(tmp_path):
    url = f"sqlite:///{tmp_path / 'lexis.db'}"
    criar_usuario(conectar(url), "ana@lexis.dev", "Ana Lima", SENHA)
    with TestClient(criar_app(configurar(tmp_path, db_url=url)), base_url=BASE) as c:
        yield c, conectar(url)


def _entrar(c: TestClient, senha: str = SENHA, login: str = "ana@lexis.dev"):
    return c.post("/api/sessao", headers=AUTH, json={"login": login, "senha": senha})


def test_sem_banco_nao_ha_login_e_o_console_segue_como_antes(tmp_path):
    with TestClient(criar_app(configurar(tmp_path)), base_url=BASE) as c:
        assert c.get("/api/sessao", headers=AUTH).json() == {"login_exigido": False, "usuario": None, "dominios_email": []}
        assert c.get("/api/saude", headers=AUTH).status_code == 200
        assert _entrar(c).status_code == 404


def test_com_banco_toda_rota_exige_sessao_e_o_token_continua_exigido(com_banco):
    c, _ = com_banco
    assert c.get("/api/sessao").status_code == 401  # sem o token Bearer nem a sessão é consultada
    assert c.get("/api/sessao", headers=AUTH).json() == {"login_exigido": True, "usuario": None, "dominios_email": []}
    r = c.get("/api/saude", headers=AUTH)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Session"
    assert c.post("/api/sessao", json={"login": "ana@lexis.dev", "senha": SENHA}).status_code == 401  # login também exige token


def test_login_abre_sessao_em_cookie_httponly_strict_e_logout_encerra(com_banco):
    c, _ = com_banco
    r = _entrar(c)
    assert r.status_code == 200 and r.json()["usuario"] == {"login": "ana@lexis.dev", "nome": "Ana Lima"}
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie
    assert SENHA not in r.text
    assert c.get("/api/saude", headers=AUTH).status_code == 200
    assert c.delete("/api/sessao", headers=AUTH).json()["usuario"] is None
    assert c.get("/api/saude", headers=AUTH).status_code == 401


def test_erro_de_login_nao_diz_se_o_usuario_existe_e_bloqueia_por_forca_bruta(com_banco):
    c, _ = com_banco
    inexistente, errada = _entrar(c, login="ninguem@lexis.dev"), _entrar(c, senha="senha-errada-longa")
    assert inexistente.status_code == errada.status_code == 401 and inexistente.json() == errada.json()
    for _ in range(modulo_servico.MAX_FALHAS_LOGIN - 1):
        _entrar(c, senha="senha-errada-longa")
    assert _entrar(c).status_code == 429  # bloqueado, mesmo com a senha certa
    assert c.cookies.get(COOKIE_SESSAO) is None


def test_execucao_e_revisao_vao_para_o_banco_com_o_operador_autenticado(com_banco):
    c, engine = com_banco
    _entrar(c)
    run = executar_amostras(c)
    r = _revisar(c, run["id"], operador="Nome Digitado Qualquer", motivos_reconhecidos=_motivos(c, run["id"]))
    assert r.status_code == 201 and (r.json()["operador"], r.json()["usuario"]) == ("Ana Lima", "ana@lexis.dev")
    with engine.connect() as con:
        docs = con.execute(select(documento.c.arquivo).where(documento.c.execucao_id == run["id"])).scalars().all()
        rev = con.execute(select(revisao.c.operador, revisao.c.usuario_id)).one()
        uid = con.execute(select(usuario.c.id).where(usuario.c.login == "ana@lexis.dev")).scalar()
    assert DOC_05 in docs and len(docs) == run["total"]
    assert (rev.operador, rev.usuario_id) == ("Ana Lima", uid)


def _cadastrar(c: TestClient, login: str = "bruno@lexis.dev", nome: str = "Bruno Reis", senha: str = SENHA):
    return c.post("/api/usuarios", headers=AUTH, json={"login": login, "nome": nome, "senha": senha})


def test_cadastro_cria_a_conta_e_ja_entra_com_ela(com_banco):
    c, _ = com_banco
    r = _cadastrar(c, login=" Bruno@Lexis.dev ")
    assert r.status_code == 201 and r.json()["usuario"] == {"login": "bruno@lexis.dev", "nome": "Bruno Reis"}
    assert "httponly" in r.headers["set-cookie"].lower() and SENHA not in r.text
    assert c.get("/api/saude", headers=AUTH).status_code == 200
    c.delete("/api/sessao", headers=AUTH)
    assert _entrar(c, login="bruno@lexis.dev").status_code == 200


def test_cadastro_recusa_login_em_uso_e_senha_fraca_sem_abrir_sessao(com_banco):
    c, _ = com_banco
    assert _cadastrar(c, login="ana@lexis.dev").status_code == 409
    curta = _cadastrar(c, senha="curta")
    assert curta.status_code == 400 and "12 caracteres" in curta.json()["detail"]
    assert _cadastrar(c, login="bruno").status_code == 400
    assert c.cookies.get(COOKIE_SESSAO) is None
    assert c.post("/api/usuarios", json={"login": "bruno@lexis.dev", "nome": "Bruno", "senha": SENHA}).status_code == 401


def test_senha_longa_demais_nunca_volta_na_resposta(com_banco):
    c, _ = com_banco
    enorme = "x" * 5000
    cadastro, login = _cadastrar(c, senha=enorme), _entrar(c, senha=enorme)
    assert cadastro.status_code == 400 and "no máximo 200" in cadastro.json()["detail"]
    assert login.status_code == 401 and login.json() == _entrar(c, senha="senha-errada-longa").json()
    assert enorme not in cadastro.text and enorme not in login.text


def test_com_dominios_configurados_so_eles_criam_conta(tmp_path):
    url = f"sqlite:///{tmp_path / 'lexis.db'}"
    config = configurar(tmp_path, db_url=url, dominios_email=("lexis.dev",))
    with TestClient(criar_app(config), base_url=BASE) as c:
        assert c.get("/api/sessao", headers=AUTH).json()["dominios_email"] == ["lexis.dev"]
        fora = _cadastrar(c, login="bruno@gmail.com")
        assert fora.status_code == 400 and fora.json()["detail"] == "use um e-mail @lexis.dev"
        assert _cadastrar(c, login="bruno@sub.lexis.dev").status_code == 400  # subdomínio não é o domínio
        assert _cadastrar(c, login="Bruno@LEXIS.dev").status_code == 201


def test_dominios_do_ambiente_aceita_lista_com_ou_sem_arroba():
    assert dominios_do_ambiente(" @Lexis.dev, filial.com ,, ") == ("lexis.dev", "filial.com")
    assert dominios_do_ambiente("") == ()


def test_sem_banco_nao_ha_cadastro(tmp_path):
    with TestClient(criar_app(configurar(tmp_path)), base_url=BASE) as c:
        assert _cadastrar(c).status_code == 404
