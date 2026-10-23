---
name: lexis-live-recording
description: 'Use when regenerating the lexis recordings (c_replay/) and the delivered batch output (f_data/b_output/) with the REAL Anthropic model: after changing prompts, tool schemas, the model or the effort level, or when recordings are missing/outdated. Covers key hygiene, a one-document smoke test, the full live run, and the checks that prove the output came from the model.'
argument-hint: 'motivo da regravação (ex.: prompt alterado)'
---

# Regravar com o modelo real (lexis)

O lote entregue em `f_data/b_output/` e as gravações em `c_replay/` têm de vir do modelo, não de leitura manual.
Esta skill regrava tudo de forma reproduzível e verificável.

## Pré-requisitos (segurança primeiro)
- Chave **só** em `.env` (está no `.gitignore`). **Nunca** em `.env.example`, código, fixture, log ou commit.
  Confira antes: `git diff --stat` não pode listar `.env`; `git diff .env.example` não pode conter `sk-ant-`.
- Chave de usuário (`sk-ant-usr-...`) não é vinculada a workspace: defina `ANTHROPIC_WORKSPACE_ID` no `.env`
  (sem ele a API devolve 400 e o pipeline registra `REQUISICAO_REJEITADA`). Chave de workspace dispensa.
- Modelo e parâmetros vêm do ambiente: `LEXIS_MODEL`, `LEXIS_EFFORT`, `LEXIS_FALLBACKS`, `LEXIS_MAX_TOKENS`,
  `LEXIS_TIMEOUT_S` (use ≥ 120 s: as respostas não são em streaming).
- Custo: 8 documentos ≈ 20 requisições (extração + function calling; o scan faz 3 leituras). O custo estimado
  de cada documento sai em `auditoria.custo_estimado_usd`; o orçamento `LEXIS_TOKEN_BUDGET` aborta o lote.

## 1. Fumaça (1 documento, fora do repositório)
Rode um documento com `--replay` e `--saida` apontando para uma pasta temporária. Só siga se a decisão não for
`FALHA_PROCESSAMENTO` e `auditoria.chamadas_de_tools` tiver origem `MODELO`.
```bash
set -a; source .env; set +a
lexis run --modo live --forcar --entrada <pasta com 1 pdf> --replay <tmp>/replay --saida <tmp>/saida
```
Em `REQUISICAO_REJEITADA` (HTTP 400), descubra o motivo numa chamada isolada que imprime só `e.body["error"]["message"]`
(o pipeline não grava mensagens do provedor de propósito).

## 2. Lote completo
```bash
lexis run --modo live --forcar     # regrava c_replay/<sha>/*.json e regera f_data/b_output/
lexis run                          # replay: precisa reproduzir o MESMO resultado sem rede nem chave
lexis avaliar
```

## 3. Provas de que a saída veio do modelo (todas obrigatórias)
- Nenhuma gravação simulada: `grep -rl SIMULADA_MANUALMENTE c_replay/` vazio; todas com `"origem": "API"`.
- Cada documento tem `validacao_tools.json`; o scan (07) tem `transcricao`, `extracao_transcricao`, `extracao_direta`.
- Nos JSONs: `versoes.modelo` é o modelo real; `auditoria.chamadas_llm[*]` com tokens > 0 na execução live;
  `chamadas_de_tools[*].origem == "MODELO"` (as de `ORQUESTRADOR` são a rede de segurança: explique cada uma).
- `relatorio_excecoes.md` sem o aviso de "gravações simuladas"; `resumo_execucao.json` com `extracoes_simuladas: false`.
- Decisão diferente da gravação anterior é **resultado**, não bug a esconder: releia o PDF e investigue se é leitura do
  modelo (então a saída deve ir para revisão humana) ou uma regra errada. Nunca ajuste um teste para bater com a saída
  sem reler o documento. Em operação, a medida é a auditoria amostral (`lexis auditoria`), não uma planilha de respostas.

## 4. Antes do commit
```bash
ruff check a_src/b_backend b_tests && mypy && pytest -q
git status --short   # .env NÃO pode aparecer; c_replay/ e f_data/b_output/ sim
```
Atualize no README a tabela "Resultado sobre o lote", as métricas de avaliação e o custo/tokens reais.
