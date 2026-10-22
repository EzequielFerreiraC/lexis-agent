"""Projeção no banco SQL, auditoria amostral e usuários (SQLite em arquivo; o mesmo SQL roda no MySQL do compose)."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text, update

from b_tests.conftest import RAIZ
from lexis.g_adapters import sql_users
from lexis.g_adapters.local_storage import ArmazenamentoLocal, ArmazenamentoMemoria
from lexis.g_adapters.sql_schema import auditoria_amostral, campo, documento, revisao, sessao, usuario
from lexis.g_adapters.sql_store import (
    conectar,
    metricas,
    pendentes,
    projetar_execucao,
    registrar_veredito,
    sortear_auditoria,
    wilson,
)
from lexis.h_interfaces import contracts

LOTE = RAIZ / "f_data" / "b_output" / "report_261023_2135"


@pytest.fixture
def engine(tmp_path):
    return conectar(f"sqlite:///{tmp_path / 'lexis.db'}")


def _contar(engine, tabela, *onde):
    with engine.connect() as con:
        return con.execute(select(func.count()).select_from(tabela).where(*onde)).scalar()


def test_projeta_o_lote_com_campos_evidencia_e_colunas_tipadas(engine):
    r = projetar_execucao(engine, LOTE.name, ArmazenamentoLocal(LOTE))
    assert (r.documentos, r.revisoes) == (8, 0)
    with engine.connect() as con:
        doc02 = con.execute(select(documento).where(documento.c.arquivo == "02_banco_meridional_jcp.pdf")).one()
        bruto = con.execute(select(campo).where(campo.c.documento_id == doc02.id, campo.c.nome == "valor_bruto")).one()
    assert (doc02.decisao, doc02.tipo_evento, doc02.isin, doc02.moeda) == ("APROVADO_AUTO", "JCP", "BRBMRDACNPR7", "BRL")
    assert str(doc02.data_pagamento) == "2026-08-14" and doc02.registro["documento"]["sha256"] == doc02.sha256
    assert bruto.pagina == 1 and bruto.trecho and bruto.confianca in {"ALTA", "MEDIA"}
    assert _contar(engine, documento, documento.c.decisao == "REVISAO_HUMANA") == 3


def test_reimportar_e_idempotente_e_preserva_auditoria(engine):
    projetar_execucao(engine, LOTE.name, ArmazenamentoLocal(LOTE))
    sorteados = sortear_auditoria(engine, 1.0, "s")
    projetar_execucao(engine, LOTE.name, ArmazenamentoLocal(LOTE))
    assert _contar(engine, documento) == 8 and _contar(engine, auditoria_amostral) == len(sorteados)
    with engine.connect() as con:
        ids = set(con.execute(select(auditoria_amostral.c.documento_id)).scalars())
    assert ids == set(sorteados)  # mesmos documento.id: a reimportação atualiza no lugar


def test_texto_do_documento_nunca_vira_sql(engine):
    bruto = json.loads((LOTE / "json" / "01_energetica_vale_tiete_dividendo.json").read_text(encoding="utf-8"))
    bruto["campos"]["emissor"]["valor"] = "X'); DROP TABLE documento; --"
    armazem = ArmazenamentoMemoria({"json/01.json": json.dumps(bruto).encode()})
    projetar_execucao(engine, "exec_injecao", armazem)
    with engine.connect() as con:
        assert con.execute(select(documento.c.emissor)).scalar() == "X'); DROP TABLE documento; --"


def test_revisoes_do_console_sao_projetadas_uma_vez(engine):
    linha = {"arquivo": "05_aurora_saneamento_dividendo_datas.pdf", "decisao": "REJEITADO_NA_REVISAO",
             "operador": "Ana", "justificativa": "pagamento antes da data com", "revisada_em": "2026-10-23T10:00:00+00:00",
             "sha256_registro": "a" * 64}
    assert projetar_execucao(engine, LOTE.name, ArmazenamentoLocal(LOTE), [linha]).revisoes == 1
    assert projetar_execucao(engine, LOTE.name, ArmazenamentoLocal(LOTE), [linha]).revisoes == 0
    assert _contar(engine, revisao) == 1


def test_sorteio_so_de_aprovados_estratificado_reproduzivel_e_sem_repeticao(tmp_path):
    a, b = (conectar(f"sqlite:///{tmp_path / n}") for n in ("a.db", "b.db"))
    for e in (a, b):
        projetar_execucao(e, LOTE.name, ArmazenamentoLocal(LOTE))
    sa, sb = sortear_auditoria(a, 0.01, "semente-1"), sortear_auditoria(b, 0.01, "semente-1")
    assert sa == sb  # mesma semente, mesma amostra
    with a.connect() as con:
        estratos = set(con.execute(select(auditoria_amostral.c.estrato)).scalars())
        decisoes = set(con.execute(select(documento.c.decisao).where(documento.c.id.in_(sa))).scalars())
    assert decisoes == {"APROVADO_AUTO"}
    assert "JCP/SCAN" in estratos and len(sa) == len(estratos)  # taxa baixa ainda cobre cada estrato
    assert set(sortear_auditoria(a, 1.0, "outra")).isdisjoint(sa)  # quem já foi sorteado não volta


def test_veredito_exige_campo_quando_errado_e_nao_se_reescreve(engine):
    projetar_execucao(engine, LOTE.name, ArmazenamentoLocal(LOTE))
    sortear_auditoria(engine, 1.0, "s")
    primeiro, segundo = (p["id"] for p in pendentes(engine)[:2])
    with pytest.raises(ValueError, match="campo errado"):
        registrar_veredito(engine, primeiro, "ERRADO", "Bia")
    registrar_veredito(engine, primeiro, "ERRADO", "Bia", campo_errado="valor_bruto", valor_correto="0.43")
    registrar_veredito(engine, segundo, "CORRETO", "Bia")
    with pytest.raises(ValueError, match="já registrada"):
        registrar_veredito(engine, primeiro, "CORRETO", "Bia")
    m = metricas(engine)["auditoria_amostral"]
    assert (m["auditados"], m["erros"], m["taxa_falso_auto_aprovado"]) == (2, 1, 0.5)


def test_wilson_nao_colapsa_em_zero_com_amostra_pequena():
    baixo, alto = wilson(0, 10)
    assert baixo == 0.0 and alto > 0.25  # 0 erros em 10 não prova taxa zero
    assert wilson(0, 0) is None


def test_metricas_de_abstencao(engine):
    projetar_execucao(engine, LOTE.name, ArmazenamentoLocal(LOTE))
    m = metricas(engine)
    assert m["documentos"] == 8 and m["taxa_abstencao"] == 0.5 and m["auditoria_amostral"]["ic95"] is None


def test_ddl_mysql_publicado_acompanha_o_esquema():
    assert contracts.DESTINO_DDL.read_text(encoding="utf-8") == contracts.ddl_mysql(), "rode `lexis contratos`"
    assert "ENGINE=InnoDB" in contracts.ddl_mysql() and "FOREIGN KEY" in contracts.ddl_mysql()


def test_cada_consulta_documentada_roda_contra_o_lote(engine):
    projetar_execucao(engine, LOTE.name, ArmazenamentoLocal(LOTE))
    sortear_auditoria(engine, 1.0, "s")
    resultados = {}
    with engine.connect() as con:
        for nome, sql in contracts.consultas().items():
            resultados[nome] = con.execute(text(sql), {"isin": "BRBMRDACNPR7"}).all()
    assert len(resultados) == 7
    fila = resultados["fila_de_revisao_por_prazo"]
    datas = [r.data_pagamento for r in fila]
    assert len(fila) == 4 and datas[-1] is None  # sem data de pagamento vai para o fim
    assert [d for d in datas if d is not None] == sorted(d for d in datas if d is not None)
    assert [r.arquivo for r in resultados["historico_por_isin"]] == ["02_banco_meridional_jcp.pdf"]
    assert {r.regra_id for r in resultados["regras_que_mais_bloqueiam"]} >= {"GOLDEN_NAO_ENCONTRADO"}


# ----------------------------------------------------------------------- usuários

SENHA = "uma-senha-longa-o-bastante"


def test_senha_fica_so_em_hash_com_sal(engine):
    sql_users.criar_usuario(engine, "ana@lexis.dev", "Ana Lima", SENHA)
    sql_users.criar_usuario(engine, "bia@lexis.dev", "Bia Reis", SENHA)
    with engine.connect() as con:
        hashes = list(con.execute(select(usuario.c.senha_hash)).scalars())
    assert all(SENHA not in h and h.startswith("scrypt$") for h in hashes) and hashes[0] != hashes[1]


@pytest.mark.parametrize(("login", "senha", "erro"), [
    ("ana@lexis.dev", "curta", "12 caracteres"), ("ana@lexis.dev", "ana-com-senha-longa", "não pode conter o seu e-mail"),
    ("ana", SENHA, "e-mail inválido"), ("Ana Lima@lexis.dev", SENHA, "e-mail inválido"),
    ("ana@lexis", SENHA, "e-mail inválido"), ("a" * 250 + "@x.dev", SENHA, "e-mail inválido"),
])
def test_criacao_recusa_login_e_senha_fracos(engine, login, senha, erro):
    with pytest.raises(ValueError, match=erro):
        sql_users.criar_usuario(engine, login, "Ana", senha)


def test_autenticacao_e_sessao(engine):
    u = sql_users.criar_usuario(engine, "ana@lexis.dev", "Ana Lima", SENHA)
    assert sql_users.autenticar(engine, "ana@lexis.dev", "errada-mas-longa") is None
    assert sql_users.autenticar(engine, "ninguem@lexis.dev", SENHA) is None
    assert sql_users.autenticar(engine, " ANA@Lexis.DEV ", SENHA) == u
    token = sql_users.abrir_sessao(engine, u)
    with engine.connect() as con:
        assert token not in set(con.execute(select(sessao.c.token_sha256)).scalars())  # só o hash
    assert sql_users.usuario_da_sessao(engine, token) == u
    assert sql_users.usuario_da_sessao(engine, token + "x") is None
    sql_users.encerrar_sessao(engine, token)
    assert sql_users.usuario_da_sessao(engine, token) is None


def test_sessao_expirada_ou_de_usuario_inativo_nao_vale(engine):
    u = sql_users.criar_usuario(engine, "ana@lexis.dev", "Ana Lima", SENHA)
    t1, t2 = sql_users.abrir_sessao(engine, u), sql_users.abrir_sessao(engine, u)
    with engine.begin() as con:
        con.execute(update(sessao).where(sessao.c.token_sha256 == sql_users._sha(t1))
                    .values(expira_em=sql_users.agora_utc() - timedelta(seconds=1)))
    assert sql_users.usuario_da_sessao(engine, t1) is None and sql_users.usuario_da_sessao(engine, t2) == u
    with engine.begin() as con:
        con.execute(update(usuario).values(ativo=False))
    assert sql_users.usuario_da_sessao(engine, t2) is None
