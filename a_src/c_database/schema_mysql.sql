-- Gerado por `lexis contratos` a partir de lexis/g_adapters/sql_schema.py. Não edite à mão.
-- utf8mb4: o texto dos avisos tem acentos; InnoDB: chaves estrangeiras e transações.

CREATE TABLE execucao (
	id VARCHAR(40) NOT NULL COMMENT 'pasta da execução (report_yymmdd_hhmm)', 
	run_id VARCHAR(32) NOT NULL, 
	importada_em DATETIME NOT NULL, 
	modo VARCHAR(10), 
	versao_pipeline VARCHAR(20), 
	versao_regras VARCHAR(40), 
	prompt_sha VARCHAR(20), 
	modelo VARCHAR(60), 
	golden_sha VARCHAR(20), 
	schema_version VARCHAR(10), 
	total_documentos INTEGER NOT NULL, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE usuario (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	login VARCHAR(254) NOT NULL COMMENT 'e-mail, em minúsculas', 
	nome VARCHAR(80) NOT NULL, 
	senha_hash VARCHAR(255) NOT NULL COMMENT 'scrypt com sal; nunca a senha', 
	ativo BOOL NOT NULL, 
	criado_em DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (login)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE documento (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	execucao_id VARCHAR(40) NOT NULL, 
	arquivo VARCHAR(255) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	sha256_registro VARCHAR(64) NOT NULL COMMENT 'hash do JSON projetado: liga a linha ao arquivo selado', 
	paginas INTEGER, 
	fonte VARCHAR(10) COMMENT 'NATIVO | SCAN', 
	decisao VARCHAR(20) NOT NULL, 
	linha_da_tabela VARCHAR(80), 
	resumo TEXT, 
	tipo_evento VARCHAR(20), 
	golden_status VARCHAR(20), 
	emissor VARCHAR(200), 
	isin VARCHAR(12), 
	ticker VARCHAR(12), 
	data_com DATE, 
	data_ex DATE, 
	data_pagamento DATE, 
	valor_bruto NUMERIC(20, 10), 
	moeda VARCHAR(3), 
	confianca_minima VARCHAR(10) COMMENT 'menor nível entre os campos extraídos', 
	registro JSON NOT NULL COMMENT 'o registro completo, como no JSON selado', 
	PRIMARY KEY (id), 
	CONSTRAINT uq_documento_execucao_arquivo UNIQUE (execucao_id, arquivo), 
	CONSTRAINT ck_documento_decisao CHECK (decisao IN ('APROVADO_AUTO','AGUARDA_EMISSOR','REVISAO_HUMANA','FALHA_PROCESSAMENTO')), 
	FOREIGN KEY(execucao_id) REFERENCES execucao (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE INDEX ix_documento_evento ON documento (emissor, tipo_evento, data_com);
CREATE INDEX ix_documento_fila ON documento (decisao, data_pagamento);
CREATE INDEX ix_documento_isin ON documento (isin);
CREATE INDEX ix_documento_sha256 ON documento (sha256);

CREATE TABLE sessao (
	token_sha256 VARCHAR(64) NOT NULL COMMENT 'só o hash: o token em si fica no cookie', 
	usuario_id BIGINT NOT NULL, 
	criada_em DATETIME NOT NULL, 
	expira_em DATETIME NOT NULL, 
	PRIMARY KEY (token_sha256), 
	FOREIGN KEY(usuario_id) REFERENCES usuario (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE INDEX ix_sessao_expira ON sessao (expira_em);

CREATE TABLE auditoria_amostral (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	documento_id BIGINT NOT NULL, 
	estrato VARCHAR(40) NOT NULL COMMENT 'tipo de evento + fonte (NATIVO/SCAN)', 
	sorteada_em DATETIME NOT NULL, 
	semente VARCHAR(64) NOT NULL COMMENT 'reproduz o sorteio', 
	veredito VARCHAR(10) COMMENT 'NULL = pendente | CORRETO | ERRADO', 
	campo_errado VARCHAR(40), 
	valor_correto VARCHAR(400), 
	observacao TEXT, 
	auditor VARCHAR(80), 
	registrada_em DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_auditoria_veredito CHECK (veredito IS NULL OR veredito IN ('CORRETO','ERRADO')), 
	UNIQUE (documento_id), 
	FOREIGN KEY(documento_id) REFERENCES documento (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE INDEX ix_auditoria_pendentes ON auditoria_amostral (veredito, estrato);

CREATE TABLE campo (
	documento_id BIGINT NOT NULL, 
	nome VARCHAR(40) NOT NULL, 
	estado VARCHAR(15) NOT NULL COMMENT 'EXTRAIDO | NAO_APLICAVEL | AUSENTE | PENDENTE | INCERTO', 
	valor VARCHAR(400), 
	natureza VARCHAR(10), 
	confianca VARCHAR(10) NOT NULL, 
	justificativa TEXT, 
	pagina INTEGER, 
	trecho VARCHAR(400) COMMENT 'trecho literal citado (evidência)', 
	PRIMARY KEY (documento_id, nome), 
	FOREIGN KEY(documento_id) REFERENCES documento (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE INDEX ix_campo_estado_confianca ON campo (nome, estado, confianca);

CREATE TABLE motivo (
	documento_id BIGINT NOT NULL, 
	ordem INTEGER NOT NULL, 
	codigo VARCHAR(60) NOT NULL, 
	campo VARCHAR(40), 
	mensagem TEXT, 
	PRIMARY KEY (documento_id, ordem), 
	FOREIGN KEY(documento_id) REFERENCES documento (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE regra_resultado (
	documento_id BIGINT NOT NULL, 
	regra_id VARCHAR(60) NOT NULL, 
	severidade VARCHAR(10) NOT NULL, 
	resultado VARCHAR(15) NOT NULL COMMENT 'OK | FALHA | NAO_APLICAVEL', 
	detalhe TEXT, 
	PRIMARY KEY (documento_id, regra_id), 
	FOREIGN KEY(documento_id) REFERENCES documento (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE INDEX ix_regra_falhas ON regra_resultado (regra_id, resultado);

CREATE TABLE revisao (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	documento_id BIGINT NOT NULL, 
	decisao VARCHAR(25) NOT NULL COMMENT 'APROVADO_NA_REVISAO | REJEITADO_NA_REVISAO', 
	operador VARCHAR(80) NOT NULL, 
	usuario_id BIGINT COMMENT 'preenchido quando o operador estava autenticado', 
	justificativa TEXT NOT NULL, 
	revisada_em DATETIME NOT NULL, 
	sha256_registro VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (documento_id), 
	FOREIGN KEY(documento_id) REFERENCES documento (id) ON DELETE CASCADE, 
	FOREIGN KEY(usuario_id) REFERENCES usuario (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
