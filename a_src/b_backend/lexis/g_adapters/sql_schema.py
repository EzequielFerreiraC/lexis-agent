"""Esquema SQL da projeção consultável (MySQL 8.4 no compose; SQLite nos testes; SQL Server trocando o driver).

Os JSONs selados de cada execução continuam sendo o registro oficial e auditável. O banco é uma **projeção** deles,
reconstruível a qualquer momento (`lexis db importar`), para o que não escala em arquivos: fila de revisão por prazo,
histórico por emissor/ISIN, duplicatas entre execuções, auditoria amostral e métricas. Usuários e sessões do console
só existem aqui.

SQL portátil (SQLAlchemy Core): nada de tipo ou função de um banco só. O DDL para MySQL é publicado em
a_src/c_database/schema_mysql.sql por `lexis contratos`.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

# BIGINT no MySQL/SQL Server; INTEGER no SQLite (só ele faz autoincremento de INTEGER PRIMARY KEY)
Id = BigInteger().with_variant(Integer(), "sqlite")
DECISOES = "'APROVADO_AUTO','AGUARDA_EMISSOR','REVISAO_HUMANA','FALHA_PROCESSAMENTO'"

execucao = Table(
    "execucao", metadata,
    Column("id", String(40), primary_key=True, comment="pasta da execução (report_yymmdd_hhmm)"),
    Column("run_id", String(32), nullable=False),
    Column("importada_em", DateTime, nullable=False),
    Column("modo", String(10)),
    Column("versao_pipeline", String(20)),
    Column("versao_regras", String(40)),
    Column("prompt_sha", String(20)),
    Column("modelo", String(60)),
    Column("golden_sha", String(20)),
    Column("schema_version", String(10)),
    Column("total_documentos", Integer, nullable=False),
)

documento = Table(
    "documento", metadata,
    Column("id", Id, primary_key=True, autoincrement=True),
    Column("execucao_id", String(40), ForeignKey("execucao.id", ondelete="CASCADE"), nullable=False),
    Column("arquivo", String(255), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("sha256_registro", String(64), nullable=False, comment="hash do JSON projetado: liga a linha ao arquivo selado"),
    Column("paginas", Integer),
    Column("fonte", String(10), comment="NATIVO | SCAN"),
    Column("decisao", String(20), nullable=False),
    Column("linha_da_tabela", String(80)),
    Column("resumo", Text),
    Column("tipo_evento", String(20)),
    Column("golden_status", String(20)),
    Column("emissor", String(200)),
    Column("isin", String(12)),
    Column("ticker", String(12)),
    Column("data_com", Date),
    Column("data_ex", Date),
    Column("data_pagamento", Date),
    Column("valor_bruto", Numeric(20, 10)),
    Column("moeda", String(3)),
    Column("confianca_minima", String(10), comment="menor nível entre os campos extraídos"),
    Column("registro", JSON, nullable=False, comment="o registro completo, como no JSON selado"),
    UniqueConstraint("execucao_id", "arquivo", name="uq_documento_execucao_arquivo"),
    CheckConstraint(f"decisao IN ({DECISOES})", name="ck_documento_decisao"),
    Index("ix_documento_fila", "decisao", "data_pagamento"),
    Index("ix_documento_isin", "isin"),
    Index("ix_documento_sha256", "sha256"),
    Index("ix_documento_evento", "emissor", "tipo_evento", "data_com"),
)

campo = Table(
    "campo", metadata,
    Column("documento_id", Id, ForeignKey("documento.id", ondelete="CASCADE"), primary_key=True),
    Column("nome", String(40), primary_key=True),
    Column("estado", String(15), nullable=False, comment="EXTRAIDO | NAO_APLICAVEL | AUSENTE | PENDENTE | INCERTO"),
    Column("valor", String(400)),
    Column("natureza", String(10)),
    Column("confianca", String(10), nullable=False),
    Column("justificativa", Text),
    Column("pagina", Integer),
    Column("trecho", String(400), comment="trecho literal citado (evidência)"),
    Index("ix_campo_estado_confianca", "nome", "estado", "confianca"),
)

regra_resultado = Table(
    "regra_resultado", metadata,
    Column("documento_id", Id, ForeignKey("documento.id", ondelete="CASCADE"), primary_key=True),
    Column("regra_id", String(60), primary_key=True),
    Column("severidade", String(10), nullable=False),
    Column("resultado", String(15), nullable=False, comment="OK | FALHA | NAO_APLICAVEL"),
    Column("detalhe", Text),
    Index("ix_regra_falhas", "regra_id", "resultado"),
)

motivo = Table(
    "motivo", metadata,
    Column("documento_id", Id, ForeignKey("documento.id", ondelete="CASCADE"), primary_key=True),
    Column("ordem", Integer, primary_key=True),
    Column("codigo", String(60), nullable=False),
    Column("campo", String(40)),
    Column("mensagem", Text),
)

usuario = Table(
    "usuario", metadata,
    Column("id", Id, primary_key=True, autoincrement=True),
    Column("login", String(254), nullable=False, unique=True, comment="e-mail, em minúsculas"),
    Column("nome", String(80), nullable=False),
    Column("senha_hash", String(255), nullable=False, comment="scrypt com sal; nunca a senha"),
    Column("ativo", Boolean, nullable=False, default=True),
    Column("criado_em", DateTime, nullable=False),
)

sessao = Table(
    "sessao", metadata,
    Column("token_sha256", String(64), primary_key=True, comment="só o hash: o token em si fica no cookie"),
    Column("usuario_id", Id, ForeignKey("usuario.id", ondelete="CASCADE"), nullable=False),
    Column("criada_em", DateTime, nullable=False),
    Column("expira_em", DateTime, nullable=False),
    Index("ix_sessao_expira", "expira_em"),
)

revisao = Table(
    "revisao", metadata,
    Column("id", Id, primary_key=True, autoincrement=True),
    Column("documento_id", Id, ForeignKey("documento.id", ondelete="CASCADE"), nullable=False, unique=True),
    Column("decisao", String(25), nullable=False, comment="APROVADO_NA_REVISAO | REJEITADO_NA_REVISAO"),
    Column("operador", String(80), nullable=False),
    Column("usuario_id", Id, ForeignKey("usuario.id"), comment="preenchido quando o operador estava autenticado"),
    Column("justificativa", Text, nullable=False),
    Column("revisada_em", DateTime, nullable=False),
    Column("sha256_registro", String(64), nullable=False),
)

auditoria_amostral = Table(
    "auditoria_amostral", metadata,
    Column("id", Id, primary_key=True, autoincrement=True),
    Column("documento_id", Id, ForeignKey("documento.id", ondelete="CASCADE"), nullable=False, unique=True),
    Column("estrato", String(40), nullable=False, comment="tipo de evento + fonte (NATIVO/SCAN)"),
    Column("sorteada_em", DateTime, nullable=False),
    Column("semente", String(64), nullable=False, comment="reproduz o sorteio"),
    Column("veredito", String(10), comment="NULL = pendente | CORRETO | ERRADO"),
    Column("campo_errado", String(40)),
    Column("valor_correto", String(400)),
    Column("observacao", Text),
    Column("auditor", String(80)),
    Column("registrada_em", DateTime),
    CheckConstraint("veredito IS NULL OR veredito IN ('CORRETO','ERRADO')", name="ck_auditoria_veredito"),
    Index("ix_auditoria_pendentes", "veredito", "estrato"),
)
