# Operação: como rodar, configurar e usar

Guia de uso completo. O resumo de 5 comandos está no [README](../../README.md).

## 1. CLI

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt && pip install --no-deps -e .

lexis run                         # lote em replay (sem rede, sem chave) -> f_data/b_output/report_yymmdd_hhmm
pytest -q                         # 343 testes, sem rede (o banco nos testes é SQLite em arquivo temporário)
lexis avaliar                     # avaliação por mutação
lexis auditar f_data/b_output/report_yymmdd_hhmm   # a trilha, os registros e as decisões ainda são os gravados?
lexis contratos                   # regrava JSON Schema, OpenAPI (e_docs/e_contracts) e o DDL do MySQL (a_src/c_database)
```

Sem instalar o pacote: `PYTHONPATH=a_src/b_backend python -m lexis ...`.

| Comando | O que faz |
|---|---|
| `lexis run [--modo replay\|auto\|live] [--forcar] [--sem-ocr]` | Processa o lote |
| `lexis avaliar` | Mutação: injeta defeitos e mede se deixam de ser aprovados. Sai com código 1 se algum passar |
| `lexis auditar <pasta>` | Confere cadeia de hashes, registros contra o selo e decisões humanas. 0 = íntegra, 1 = não, 2 = pasta inexistente. Execução da CLI: a pasta `report_…`; execução do console: `report_…/saida` |
| `lexis serve [--porta N]` | Console web local (só loopback) |
| `lexis contratos` | Regrava contratos e DDL após mudança de propósito |
| `lexis db importar <pastas>` | Projeta (ou reprojeta) execuções no banco; idempotente |
| `lexis auditoria sortear\|pendentes\|registrar\|metricas` | Auditoria amostral dos `APROVADO_AUTO` (exige banco) |
| `lexis usuario criar <email> --nome "<Apelido>"` | Cria conta do console (senha pedida sem eco; exige banco). A conta também pode ser criada na tela de login |

Saídas em `f_data/b_output/report_yymmdd_hhmm/` (hora local; duas execuções no mesmo minuto ganham `_2`): `json/`, `relatorio_excecoes.md` e `.json`, `resumo_execucao.json`, `auditoria.jsonl`. `lexis avaliar` grava o `avaliacao_mutacao.json` em **uma pasta `report_…` própria** dentro de `--saida`. O cache `f_data/b_output/_cache/` (fora do Git) permite reaproveitar documentos já processados com as mesmas versões; `--forcar` o ignora e o atualiza.

## 2. Modos de extração

| Modo | Comportamento |
|---|---|
| `--modo replay` (padrão) | Usa só as gravações de `c_replay/` (`<sha256-do-PDF>/<etapa>.json`: acha a gravação mesmo se o PDF for renomeado). Falta de gravação = `FALHA_PROCESSAMENTO` explícita; gravação feita com outro prompt também (`GRAVACAO_PROMPT_DIVERGENTE`): mudou o prompt, regrave com `--modo live`, senão o replay e o CI falham |
| `--modo auto` | Usa a gravação se existir; senão chama a API e grava. Um documento 100% gravado **não exige chave nem cria cliente** |
| `--modo live` | Sempre chama a API (exige `ANTHROPIC_API_KEY`) e regrava |

Nenhum passo da **avaliação** exige chave: `lexis run` (replay), `lexis avaliar` e o modo Demonstração do console usam só as gravações.

### Regravar com o modelo real

```bash
cp .env.example .env   # preencha ANTHROPIC_API_KEY (só no .env, nunca no .env.example, que é versionado)
set -a; source .env; set +a
lexis run --modo live --forcar     # grava respostas reais em c_replay/ e gera nova pasta f_data/b_output/report_…
lexis run && lexis avaliar         # o replay precisa reproduzir o mesmo resultado; a mutação roda sobre a gravação
```

Procedimento completo (teste de fumaça, provas de que a saída veio do modelo, checklist antes do commit): skill [`lexis-live-recording`](../../.github/skills/lexis-live-recording/SKILL.md). Custa chamadas reais (≈ US$ 0,21 por lote, estimativa por preço de lista).

## 3. Variáveis de ambiente

| Variável | Para quê |
|---|---|
| `ANTHROPIC_API_KEY` | Chave da API (só por ambiente) |
| `ANTHROPIC_WORKSPACE_ID` | Só para chave de **usuário** (`sk-ant-usr-…`), que não é vinculada a um workspace; sem ele a API devolve 400 (`REQUISICAO_REJEITADA`) |
| `LEXIS_MODEL` · `LEXIS_EFFORT` · `LEXIS_FALLBACKS` · `LEXIS_MAX_TOKENS` | Modelo, profundidade de raciocínio (`medium`), fallback do servidor em recusa (`default`/`off`) e teto de saída |
| `LEXIS_TIMEOUT_S` · `LEXIS_MAX_RETRIES` · `LEXIS_TOKEN_BUDGET` | Timeout (padrão 120 s; não reduza muito: respostas não são em streaming), tentativas do SDK, orçamento de tokens do lote |
| `LEXIS_DB_URL` | Banco SQL (ex.: `mysql+pymysql://lexis:<senha>@127.0.0.1:3306/lexis?charset=utf8mb4`). Com ele, `lexis run` e o console projetam cada execução no banco e o console exige login. O compose já o define |
| `LEXIS_DB_SENHA`, `LEXIS_DB_SENHA_ROOT` | Senhas do MySQL do compose (`d_scripts/a_start.sh` as gera) |
| `LEXIS_TOKEN` | Token fixo do console (vazio = aleatório a cada subida) |
| `LEXIS_PORTA` | Porta do console no host (padrão 8000) |
| `LEXIS_DOMINIOS_EMAIL` | Com banco, só e-mails destes domínios criam conta na tela de login (ex.: `empresa.com.br,filial.com`). Vazio = qualquer domínio |
| `LEXIS_SENHA_NOVA` | Senha de `usuario criar` para automação (sem ela, pergunta sem eco) |
| `LEXIS_PRECO_ENTRADA_USD_MTOK` · `LEXIS_PRECO_SAIDA_USD_MTOK` | Sobrescreve a tabela de preços da estimativa de custo |
| `LEXIS_UID` · `LEXIS_GID` · `TZ` | Docker: uid/gid do host (padrão 1000) e fuso (`America/Sao_Paulo`) |

Variáveis da AWS (buckets, KMS, provedor): [aws.md](../c_architecture/aws.md).

## 4. OCR local (opcional)

O `pytesseract` já vem no `requirements.txt`; falta o binário: `apt install tesseract-ocr tesseract-ocr-por`. Sem ele, o pipeline degrada, registra `OCR_INDISPONIVEL` e encaminha o scan para revisão humana. O Tesseract só roda em `--modo auto`/`live`; o replay (e a avaliação) leem o OCR **gravado** em `c_replay/<sha>/ocr.json`. A imagem Docker já traz o Tesseract.

## 5. Console web (opcional, local)

Faz o mesmo que a CLI (executar o lote, abrir cada documento com a página renderizada e o trecho de cada campo destacado, ver validação, fichas de conferência, auditoria e o histórico paginado) e registra a **decisão do operador** nos documentos em revisão humana. A avaliação por mutação **não** fica no console: roda no `pytest`, na CLI e no CI. O console **não corrige campos**.

```bash
pip install --require-hashes -r requirements.txt && pip install --no-deps -e .   # inclui fastapi/uvicorn
cd a_src/a_frontend && npm ci && npm run build && cd ../..
lexis serve                        # imprime http://127.0.0.1:8000/#token=...  (abra esse endereço)
```

**Desenvolvimento do front:** `lexis serve` num terminal e `npm run dev` em `a_src/a_frontend` (Vite com proxy para `/api`). Testes: `npm test` (Vitest + Testing Library + axe), `npm run test:e2e` (Playwright contra o servidor real; exige `npx playwright install chromium`), `npm run lint`, `npm run typecheck`. Os tipos da API são gerados do contrato (`npm run gen:api`); um teste falha se o contrato ficar defasado.

**Controles de segurança do console** (detalhe e testes em [defenses.md §9–10](../f_governance/defenses.md)): só loopback; token por subida no fragmento da URL; cabeçalho `Host` conferido; login com banco (scrypt, cookie `HttpOnly`/`SameSite=Strict`, 8 h, bloqueio após 5 erros em 15 min); PDF nunca abre no navegador (servidor renderiza PNG); nada de HTML vindo do documento; CSP restritiva; o navegador nunca envia caminho; upload só PDF (20 MB × 20 arquivos); modo Ao vivo exige chave e confirmação; modelo só para leitura; chave digitada só na memória.

### Decisão do operador (revisão humana)

Num documento em `REVISAO_HUMANA`, a tela lista os motivos e pede: marcar cada motivo como conferido (obrigatório para aprovar; o servidor confere de novo), escolher `APROVADO_NA_REVISAO` ou `REJEITADO_NA_REVISAO`, justificativa (≥ 10 caracteres; e o nome, quando não há login) e confirmar num diálogo.

- O **registro do pipeline não muda**: a decisão automática continua auditável. A decisão humana fica ao lado dele, presa ao SHA-256 do registro revisado, em `execucao.json` (o que a tela mostra), `saida/revisoes.jsonl` (completa) e `saida/auditoria.jsonl` (só códigos e hashes; sem nome nem justificativa).
- Uma decisão por documento e execução (a segunda recebe 409); refazer exige nova execução.
- Com banco, a decisão também vai para a tabela `revisao`, ligada ao usuário.
- Fora de escopo, de propósito: corrigir campos e revalidar, e refletir a decisão no `relatorio_excecoes` (que descreve a execução automática).

**Limites do console:** é local; sem banco, o nome do operador é declarado (não autenticado); o estilo é próprio e sóbrio (tokens em `src/design/tokens.css`; **não** usa o logotipo nem o guia de marca do BTG, que não foram fornecidos); execuções interrompidas por reinício do servidor aparecem como falha. Para a nuvem: front estático em S3 + CloudFront e a API em Lambda/Fargate com Cognito na frente ([aws.md](../c_architecture/aws.md)).

## 6. Docker

Mesmo console e mesma CLI, sem instalar Python nem Node: só Docker com Compose.

```bash
d_scripts/a_start.sh                     # cria o .env com senhas do banco, sobe MySQL + console e imprime o endereço
docker compose run --rm cli usuario criar ana@empresa.com.br --nome "Ana Lima"   # ou crie a conta na tela de login
docker compose run --rm cli run          # lote em replay -> f_data/b_output/report_… (+ projeção no MySQL)
docker compose run --rm cli avaliar      # avaliação por mutação
docker compose down                      # mantém o volume do banco (mysql_dados); `down -v` o apaga
```

| Script | O que faz |
|---|---|
| `d_scripts/a_start.sh [--porta N] [--rebuild] [--sem-build] [--verificar]` | Cria o `.env` (permissão 600) se faltar e gera as senhas do banco vazias; `docker compose up -d --build --wait` e imprime o endereço com o token; já no ar, só mostra o endereço; container parado é iniciado de novo (token novo) |
| `d_scripts/b_stop.sh` | `docker compose stop`: para tudo (console e CLI) e mantém os containers criados |
| `d_scripts/c_destroy.sh [--imagens] [--sim] [--listar]` | `docker compose down --remove-orphans`: remove containers e rede, com confirmação; `--imagens` remove também `lexis:local`; `--listar` só mostra. Não toca em `f_data/b_output`, `c_replay/`, `.env` nem no volume do banco |

| Ponto | Como |
|---|---|
| Rede | Porta do console publicada só em `127.0.0.1`; token e cabeçalho `Host` conferidos como fora do container. O MySQL **não** publica porta |
| Banco | MySQL 8.4, `utf8mb4`, volume `mysql_dados`; o usuário `lexis` só no banco `lexis`; senhas aleatórias no `.env`, nunca na imagem nem no Git; healthcheck sem credencial |
| Container | Usuário sem root (uid/gid do host), sistema de arquivos só leitura, nenhuma capability |
| Dados | `f_data/b_output` com escrita; `c_replay/`, entrada e base só leitura no console (a CLI pode regravar `c_replay/` com `--modo live`) |
| Chave de API | Lida do `.env` em tempo de execução; o `.env` nunca entra na imagem (`.dockerignore`) |
| Dependências | As mesmas do lockfile com hashes e `npm ci` |
| Fuso | `TZ=America/Sao_Paulo` (a pasta `report_yymmdd_hhmm` usa a hora local) |

A imagem traz o Tesseract (português). Desenvolvimento do front continua fora do container (`npm run dev`).

## 7. Banco de dados (MySQL 8.4)

Projeção consultável das execuções; a **fonte da verdade** continua sendo os JSONs selados. Motivação, trade-offs e o que muda em escala: [decisions.md DEC-28](../g_decisions/decisions.md).

- **Esquema** ([sql_schema.py](../../a_src/b_backend/lexis/g_adapters/sql_schema.py); DDL do MySQL em [schema_mysql.sql](../../a_src/c_database/schema_mysql.sql), gerado por `lexis contratos`): `execucao` (versões de regras, prompt, modelo e base) · `documento` (decisão, tipo, emissor, ISIN, datas e valor **tipados**, mais o registro completo em `JSON`) · `campo` · `regra_resultado` · `motivo` · `revisao` · `auditoria_amostral` · `usuario` · `sessao`. Chaves estrangeiras, `CHECK` nas decisões, índices nas consultas reais.
- **Consultas prontas** ([consultas.sql](../../a_src/c_database/consultas.sql)): fila de revisão por prazo de pagamento, histórico por ISIN, possíveis duplicatas entre execuções, campos fracos por tipo de evento, regras que mais bloqueiam, falso aprovado automático por estrato e decisões humanas por motivo. Um teste executa todas contra o lote entregue.
- **Reconstruir:** `lexis db importar <pastas>` (idempotente: reimportar atualiza no lugar, sem perder vereditos nem revisões).
- **Opcional:** sem `LEXIS_DB_URL`, pipeline, CLI e console funcionam só com arquivos (é assim que `pytest` e o replay rodam).

### Auditoria amostral (medir o falso aprovado automático)

```bash
lexis auditoria sortear --taxa 0.05                   # sorteia, por estrato (tipo × nativo/scan), os aprovados a conferir às cegas
lexis auditoria pendentes                             # o que falta auditar, pelo prazo de pagamento
lexis auditoria registrar <id> --veredito CORRETO --auditor "Ana"
lexis auditoria registrar <id> --veredito ERRADO --auditor "Ana" --campo valor_bruto --valor "R$ 0,17"
lexis auditoria metricas                              # abstenção e falso aprovado, com IC de Wilson de 95%
```

O sorteio é reproduzível pela semente; o veredito não se reescreve; `ERRADO` exige campo e valor certo (o rótulo por campo que permite calibrar a confiança depois).

## 8. Estender o sistema

Passo a passo na skill [`lexis-extend-rules`](../../.github/skills/lexis-extend-rules/SKILL.md). Em resumo:

1. **Novo tipo** (ex.: subscrição): `TipoEvento` (`a_domain/models.py`), bloco em `rules.json` (`aplicabilidade`, `criticos`, `tratamento_tributario`) e sinais em `d_validation/classification._SINAIS`. Roteamento, schema e relatório não mudam.
2. **Nova regra:** `id`/severidade/descrição em `rules.json`, implementação em `d_validation/coherence.py`, tool em `d_validation/tools.py` e (se bloquear) linha em `e_decision/decision_table.TABELA`. Teste e, se aplicável, mutação em `i_assessment/evaluation._gerar_casos`.
3. **Mudar política:** bloco `politica` de `rules.json`.
4. **Novo destino/ambiente:** novo adaptador em `g_adapters/` que implemente a porta.
5. **Mudou o schema ou a API:** `lexis contratos` (e `npm run gen:api` no front); suba `SCHEMA_VERSION` se o schema mudou.
