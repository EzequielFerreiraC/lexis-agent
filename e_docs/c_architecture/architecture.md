# Arquitetura do Lexis

Como o código é organizado em arquitetura hexagonal (portas e adaptadores), como isso é verificado e onde cada peça externa se liga. Para o caminho de **um documento** pelo sistema, veja o [pipeline](pipeline.md); para a nuvem, [aws.md](aws.md).

[![Arquitetura](diagrams/architecture.png)](diagrams/architecture.png)

*Clique para ampliar. Fonte editável: [diagrams/architecture.mmd](diagrams/architecture.mmd).*

## Em uma frase

**Arquitetura hexagonal (portas e adaptadores).** O núcleo (`a_` a `f_`) não faz I/O: recebe bytes e dados e devolve um registro. Tudo que toca o mundo (arquivo, S3, trilha, API do modelo, OCR, variáveis de ambiente, log) é uma **porta** definida no domínio e implementada por um **adaptador** em `g_adapters/`, ligado pelas entradas (`h_interfaces/`). Por isso o mesmo código roda no terminal, no console web, em testes (memória + extrator falso) e numa Lambda.

**Garantido por teste.** [test_architecture.py](../../b_tests/a_unit/test_architecture.py) lê o código-fonte (AST) e falha se uma camada do núcleo:

- importar biblioteca de I/O (`anthropic`, `pytesseract`, `boto3`, `sqlalchemy`, `fastapi`, `httpx`, `subprocess`, `os`, `sys`…);
- importar `g_adapters`, `h_interfaces`, `i_assessment` ou uma camada acima da sua;
- chamar `open()`, `print()`, `.read_bytes()`/`.write_text()`… ou ler `os.environ`.

O próprio teste foi conferido injetando uma violação de propósito.

**Única exceção, consciente:** `a_domain/specs.py` lê `rules.json` uma vez, ao importar. O catálogo de regras é empacotado com o código (`package-data`) e versionado com hash em cada saída; tratá-lo como porta só adicionaria cerimônia.

**Também ficam fora do núcleo, por decisão:**

| Peça | Onde mora | Como entra no núcleo |
|---|---|---|
| Cliente da API do modelo (Anthropic ou Bedrock) | `g_adapters/anthropic_api.py` (`ExtratorAnthropic`, `ChamadorAnthropic`) | Fábricas `Contexto.cliente_factory` e `Contexto.chamador_factory` |
| OCR (Tesseract) | `g_adapters/tesseract_ocr.py` | Porta `LeitorOCR` → `Contexto.leitor_ocr` |
| Variáveis de ambiente | `g_adapters/ambiente.py` (`config_do_ambiente`) | `Config`, um dado puro |
| Leitura de PDF e da base do disco | `g_adapters/local_execution.py` (`ingerir_arquivo`, `carregar_golden`) | O núcleo só tem `ingerir_bytes` e `Golden.de_bytes` |
| Log do lote | `logging` (`lexis.lote`); o destino é ligado por `g_adapters/log_trail.configurar_log` | Sem handler configurado, nada é escrito |
| Banco SQL | `g_adapters/sql_*.py` | Não entra: é acionado pelas entradas (CLI e console), que leem os registros por `ArmazenamentoObjetos` |

Relógio (`datetime.now`) e gerador de ids (`uuid`) continuam chamados direto no núcleo: não são I/O, e o resultado auditável não depende deles (o teste de regressão compara o registro sem `run_id` nem timestamps).

## Camadas

Cada pasta tem prefixo de letra e só importa de letras anteriores (verificado por teste). Única exceção: `h_interfaces/cli.py` importa `i_assessment`, para `lexis avaliar`. O grafo **não é uma cadeia**: `a_domain` é a base de todos; `b_ingestion` não importa nada de `lexis`; `c_extraction`, `d_validation` e `e_decision` só importam `a_domain`; `f_application` junta `a_` a `e_`. Base: `a_src/b_backend/lexis/`.

| Camada | Responsabilidade | Peças principais |
|---|---|---|
| `a_domain` | O que o sistema *é*: modelos, portas, catálogo de regras e matemática de hash | `models.py` (contratos), `ports.py`, `rules.json` (regras, matriz de aplicabilidade, política), `normalization.py`, `hash_chain.py`, `market_calendar.py` |
| `b_ingestion` | Ler o PDF sem confiar nele (só sobre bytes) | `pdf.py` (limites, texto visível × oculto, conteúdo ativo, bbox, render) |
| `c_extraction` | O contrato com o modelo e as gravações (sem rede) | `prompts.py` (prompts e schema, com hash), `recordings.py` (gravações e replay), `costs.py`, `config.py` |
| `d_validation` | Verificar o que o modelo leu | `evidence.py`, `classification.py`, `reference_base.py`, `coherence.py`, `tools.py` (tools, allow-list e orquestrador; a conversa com o modelo vem por porta) |
| `e_decision` | Pontuar e rotear | `confidence.py`, `decision_table.py`, `checklists.py` |
| `f_application` | Orquestrar | `analysis.py` (núcleo puro), `pipeline.py` (um documento), `batch.py` (lote), `report.py`, `integrity.py` |
| `g_adapters` | Implementar as portas e montar a execução local | `local_storage.py`, `s3_storage.py`, `local_trail.py`, `log_trail.py`, `anthropic_api.py`, `tesseract_ocr.py`, `ambiente.py`, `local_execution.py`, `sql_*.py` |
| `h_interfaces` | Entradas do sistema | `cli.py`, `aws_lambda.py`, `api/` (FastAPI), `contracts.py` |
| `i_assessment` | Medir o resto (é uma entrada: lê PDFs e grava relatório) | `evaluation.py` (avaliação por mutação) |

**Regra prática:** quem precisa de algo externo recebe uma porta, nunca um caminho, um cliente ou uma variável de ambiente. Isso é exercitado pelos testes: o pipeline roda inteiro com `ArmazenamentoMemoria`, `TrilhaMemoria` e `ExtratorFalso`.

## Portas e adaptadores

| Porta (`a_domain/ports.py`) | Para quê | Adaptador local | Adaptador de nuvem |
|---|---|---|---|
| `ArmazenamentoObjetos` | PDFs, saídas, gravações, base de referência | `ArmazenamentoLocal`, `ArmazenamentoMemoria`, `ArmazenamentoComCache`, `ArmazenamentoEmCamadas` | `ArmazenamentoS3` (SSE-KMS, chaves validadas, limite por `ContentLength`) |
| `TrilhaAuditoria` | Eventos append-only | `TrilhaArquivo` (JSONL **encadeado por hash**) | `TrilhaLogsJson` (stdout → CloudWatch → Firehose → S3 Object Lock) |
| `Extrator` | Leitura por modelo (texto e imagem) | `ExtratorAnthropic` (`g_adapters/anthropic_api.py`), embrulhado por `ExtratorComCache` (gravações, `c_extraction/recordings.py`) | `AnthropicBedrock` injetado em `ExtratorAnthropic` (IAM, sem chave) |
| `ChamadorDeTools` | Function calling de validação | `ChamadorAnthropic` (`g_adapters/anthropic_api.py`), embrulhado por `ChamadorComCache` | o mesmo, sobre o cliente Bedrock |
| `LeitorOCR` | OCR do scan, independente do modelo | `tesseract_ocr.ler` (`g_adapters/`); em replay, a gravação `ocr.json` | o mesmo, na imagem de contêiner da Lambda |

Composições úteis de armazenamento:

- **`ArmazenamentoEmCamadas`**: lê do primário e, na falta, de um secundário somente leitura; **grava sempre no primário**. É como o console usa `c_replay/` como cache de leitura sem nunca sobrescrever as gravações versionadas.
- **`ArmazenamentoComCache`**: leitura no primário, depois no cache (copiando para o primário); escrita nos dois. Faz cada pasta `report_…` ficar completa mesmo com documentos reaproveitados.

## Quem chama o núcleo

| Interface | Uso | Observações de segurança |
|---|---|---|
| **CLI** `lexis` | `run`, `avaliar`, `auditar`, `contratos`, `serve`, `db importar`, `auditoria …`, `usuario criar` | Segredos só por variável de ambiente |
| **Console web** (React + FastAPI) | Executar lote, ver documento com trecho destacado, validação, fichas, auditoria, histórico, **decisão do operador** | Só loopback, token por subida, login com banco, CSP restritiva: ver [defesas](../f_governance/defenses.md) |
| **Handler Lambda** | 1 PDF por evento S3/SQS | Rejeita bucket inesperado, só `.pdf`, saída ≠ entrada. **Não implantado** |
| **Avaliação por mutação** | CI e `lexis avaliar` | Trabalha em memória sobre as gravações; sem rede |

O console **não corrige campos** e **não altera o registro do pipeline**: a decisão humana fica *ao lado* do registro, presa ao SHA-256 dele (ver [decisões](../g_decisions/decisions.md)).

## Onde os dados moram (e quem é a fonte da verdade)

| Dado | Onde | Papel |
|---|---|---|
| PDFs de entrada | `f_data/a_input/` | Entrada, somente leitura nos containers |
| Registro por documento, relatórios, `auditoria.jsonl`, `revisoes.jsonl` | `f_data/b_output/report_yymmdd_hhmm/` | **Fonte da verdade**, selada pela cadeia de hashes (`lexis auditar`) |
| Gravações das respostas do modelo e do OCR | `c_replay/<sha256>/<etapa>.json` | Reprodutibilidade (replay sem rede) |
| Base de referência | `f_data/c_golden_records/golden_records.csv` | Validação de identidade (hash gravado em cada saída) |
| Banco SQL (MySQL 8.4) | volume `mysql_dados` | **Projeção reconstruível** dos JSONs + usuários, sessões, auditoria amostral |

O banco **nunca** é segunda fonte oficial: cada linha de `documento` guarda o `sha256_registro` do JSON que a gerou, e `lexis db importar` reconstrói tudo (idempotente, sem perder vereditos nem revisões). Se a projeção falhar, a execução continua válida.

## Implantação

| Modo | Como | Estado |
|---|---|---|
| Local (pip) | `lexis run`, `lexis serve` | Testado |
| Docker Compose | `d_scripts/a_start.sh` → MySQL + console; `docker compose run --rm cli …` | Testado; usuário não-root, FS somente leitura, sem capabilities, porta só em `127.0.0.1` |
| AWS | S3 → SQS (+DLQ) → Lambda; Bedrock; CloudWatch → Firehose → S3 Object Lock | **Preparado, não implantado**, testado só com clientes falsos: [aws.md](aws.md) |

## Como estender sem quebrar a arquitetura

1. **Novo destino ou provedor** → novo adaptador em `g_adapters/` que implementa a porta (armazenamento, trilha, `Extrator`/`ChamadorDeTools`, `LeitorOCR`), ligado no `Contexto` pela entrada que o usa. As regras não mudam, e o teste de arquitetura impede que o adaptador vaze para o núcleo.
2. **Novo tipo de evento** → `TipoEvento` + bloco em `rules.json` + sinais em `classification._SINAIS`.
3. **Nova regra** → `rules.json` + `coherence.py` + tool em `tools.py` + (se bloqueia) linha em `decision_table.TABELA` e mutação em `evaluation.py`.
4. **Mudou o schema de saída ou a API** → `lexis contratos` (e `npm run gen:api` no front); o CI falha se o contrato ficar defasado.

Passo a passo completo: skill [`lexis-extend-rules`](../../.github/skills/lexis-extend-rules/SKILL.md).

## Regenerar os diagramas

```bash
npm i @mermaid-js/mermaid-cli    # fora do repositório
echo '{"args":["--no-sandbox"]}' > puppeteer.json
npx mmdc -i e_docs/c_architecture/diagrams/architecture.mmd -o e_docs/c_architecture/diagrams/architecture.png \
  -p puppeteer.json -C e_docs/c_architecture/diagrams/style.css -w 2400 -s 2 -b white
```

Os `.mmd` também renderizam direto no GitHub e no VS Code (extensão Mermaid).
