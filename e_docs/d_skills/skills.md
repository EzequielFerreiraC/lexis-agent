# Skills, ferramentas e bibliotecas

Pedido do primeiro prompt (§7): diferenciar **skills**, **bibliotecas**, **ferramentas de desenvolvimento** e **serviços externos**;
informar fonte, etapa, benefício, limites e se é essencial/recomendada/opcional. Nenhuma skill de terceiros foi instalada; só as
skills já disponíveis no ambiente do VS Code/Copilot e o subagente de revisão.

## 1. Skills e agentes (como o projeto é *desenvolvido*)

| Nome | Fonte | Etapa | Benefício concreto aqui | Limites | Classe |
|---|---|---|---|---|---|
| `python-fact-grounded-coding` | skill do ambiente (plugin Python/Pylance do VS Code) | implementação e correção | exige fatos (diagnósticos, execução) antes de concluir. **Resultado real:** mostrou que o Pylance do editor usava outro interpretador (`anthropic` "não resolvido") e que o refactoring não enxerga arquivos novos, por isso `mypy`/`ruff`/testes ficaram como verificação | depende do Pylance enxergar o workspace (aqui, um WSL) | recomendada |
| `agent-customization` | skill do ambiente; [docs](https://code.visualstudio.com/docs/copilot/customization/agent-skills) | organização | gerou [`copilot-instructions.md`](../../.github/copilot-instructions.md) (regras sempre ativas) e a skill de projeto [`lexis-extend-rules`](../../.github/skills/lexis-extend-rules/SKILL.md) | só vale se quem continuar usar um agente compatível | recomendada |
| `lexis-extend-rules` | **deste repositório** (`.github/skills/`) | extensão ao vivo | passo a passo para novo tipo de evento/regra/política, com os testes que o prendem | cobre só o fluxo de extensão | recomendada |
| subagente `security-review` | agente do ambiente | segurança | achou **2 furos reais** na detecção de texto oculto (branco em CMYK e modo `3 Tr`); corrigidos com teste | achados de alta confiança apenas; não substitui pentest | **essencial** |
| subagente `code-review` | agente do ambiente | revisão | revisa bugs de alta confiança nas mudanças de portas/AWS | idem | recomendada |
| `python-add-type-annotations`, `python-type-inference` | skills do ambiente | tipagem | não necessárias: o código já está em `mypy --strict` | só ajudariam em código novo sem tipos | opcional |
| `python-write-stubs` | skill do ambiente | tipagem de libs | `pytesseract`/`boto3` sem stubs hoje usam `ignore_missing_imports` | stubs parciais dão manutenção | opcional |
| `pylance-python-profiling` | skill do ambiente | desempenho | não houve gargalo; o tempo é dominado pela chamada ao modelo | requer Python 3.15+ para parte dos recursos | opcional |
| `troubleshoot` | skill do ambiente | diagnóstico do agente | não houve comportamento inesperado do agente | — | opcional |

### Refatoração "extração e function calling pelo modelo real" (Claude Code)

| Nome | Fonte | Etapa | Benefício concreto aqui | Limites | Classe |
|---|---|---|---|---|---|
| `claude-api` | skill do ambiente (Claude Code) | implementação da integração | referência atual do SDK: `tool_choice` forçado e amostragem rejeitados, `effort`, `fallbacks` do servidor, `stop_reason` `refusal`/`max_tokens`, loop manual com todos os `tool_result` numa mensagem e o conteúdo do assistente devolvido intacto | não substitui testar contra a API: os limites do `strict` (16 anuláveis, 24 opcionais, gramática) só apareceram nas chamadas reais | **essencial** |
| `lexis-function-calling` | **deste repositório** (`.github/skills/`) | manutenção do loop de tools | invariantes (allow-list, argumentos iguais ao extraído, veredito do código, ordem do schema no strict, replay honesto) e os testes que prendem cada um | cobre só as tools de validação | recomendada |
| `lexis-live-recording` | **deste repositório** (`.github/skills/`) | regravação com o modelo real | higiene da chave, fumaça em 1 documento fora do repositório, lote, provas de que a saída veio do modelo, checklist antes do commit | custa chamadas reais (≈ US$ 0,21 por lote) | recomendada |

Fora do escopo, por política: instalar skills de terceiros, executar código de terceiros ou conceder permissões extras exige aprovação
do dono do repositório (consta em `copilot-instructions.md`).

## 2. Bibliotecas (runtime)

| Biblioteca | Para quê | Por que esta | Alternativa/risco | Classe |
|---|---|---|---|---|
| `pydantic` v2 | contratos estritos de entrada do modelo e da saída | `extra=forbid`, enums, JSON Schema exportável para o contrato | — | essencial |
| `pdfplumber` (MIT) | texto, coordenadas (bbox), cor/tamanho de fonte (texto oculto), render da página | é o que permite detectar texto invisível e citar a caixa; PyMuPDF foi descartado por ser AGPL | mais lento que PyMuPDF | essencial |
| `anthropic` | cliente do modelo (API direta e Bedrock) | SDK oficial; `AnthropicBedrock` para a AWS | acoplamento ao provedor isolado no adaptador `g_adapters/anthropic_api.py` (o teste de arquitetura impede o núcleo de importar `anthropic`) | essencial |
| `pillow` | imagem do scan | dependência do render | — | essencial |
| `pytesseract` + binário `tesseract` | segundo leitor independente do modelo no scan | único leitor sem erro correlacionado com o LLM | binário de sistema: vem na imagem Docker; fora dela, opcional (sem ele, degrada com `OCR_INDISPONIVEL`) | `pytesseract` no `requirements.txt` (extra `ocr`) |
| `boto3` | S3 e Secrets Manager | cliente oficial da AWS | só importado sob demanda (extra `aws`) | opcional |
| `fastapi` + `uvicorn` + `python-multipart` | API HTTP local do console web (`lexis serve`) | contrato OpenAPI gerado dos modelos Pydantic (alimenta os tipos do front); `python-multipart` só para o upload | só no extra `web`; escuta apenas em loopback, com token | opcional (extra `web`) |
| `sqlalchemy` 2.0 (Core) + `pymysql` | projeção SQL das execuções, usuários e sessões, auditoria amostral | SQL portátil sem tipo/função de um banco só: MySQL no compose, SQLite nos testes, SQL Server trocando o driver; consultas sempre parametrizadas | só no extra `db`; o banco é projeção, não fonte da verdade | opcional (extra `db`) |

### Front-end (`a_src/a_frontend`, extra opcional)

| Biblioteca | Para quê | Por que esta | Classe |
|---|---|---|---|
| `react` 19 + `react-router-dom` | telas e rotas (executar, execução, documento, histórico, configurações, login) | o front tem estado de servidor e navegação suficientes para justificar um framework; React escapa texto por padrão (texto de PDF nunca vira HTML) | essencial |
| `@tanstack/react-query` | polling da execução em andamento (1 s), cache das páginas renderizadas | evita escrever à mão estados de carregamento/erro/cancelamento; `staleTime` evita refazer a renderização das páginas | essencial |
| `@radix-ui/react-tabs` | abas acessíveis (setas, `aria-*`) | teclado e leitor de tela corretos sem reimplementar; **não injeta `<style>`**, então é compatível com a CSP (`@radix-ui/react-dialog` foi descartado por injetar estilo; o diálogo usa `<dialog>` nativo) | recomendada |
| `openapi-typescript` | tipos TS gerados do OpenAPI do backend | o contrato é uma fonte só; CI falha se defasar | recomendada |
| Vite, TypeScript (strict), ESLint (`typescript-eslint` strict + `jsx-a11y`), Prettier | build, tipos, lint, formato | `no-dangerouslySetInnerHTML` e `noUncheckedIndexedAccess` são regras de segurança/robustez, não estilo | essencial |
| Vitest + Testing Library + `axe-core`, Playwright + `@axe-core/playwright` | testes de unidade/integração e de ponta a ponta com Chromium real | axe nas telas e abas; o e2e confere CSP sem violações e contraste (que o jsdom não calcula) | essencial |

Não usamos biblioteca de componentes nem de estilos (MUI, Tailwind etc.): o CSS é próprio, com *design tokens* em um arquivo
(`src/design/tokens.css`), para respeitar a CSP (`style-src 'self'`) e permitir trocar a identidade visual em um só lugar.

## 3. Ferramentas de desenvolvimento

`pytest` + `pytest-cov` (testes) · `ruff` (lint) · `mypy --strict` (tipos) · `pip-audit` (vulnerabilidades) · `pip-tools`
(lockfile com hashes) · `reportlab` (só para gerar PDFs sintéticos de teste) · `httpx` (cliente de teste da API) · `gitleaks`
(segredos, no CI) · `npm audit` (dependências do front, no CI).
Todos essenciais ou recomendados; nenhum entra no pacote de produção.

## 4. Serviços externos

| Serviço | Uso | Dado enviado | Controle |
|---|---|---|---|
| API da Anthropic | extração por modelo (texto e imagem) | conteúdo do documento | chave só por env; DPA/zero-retention em produção |
| AWS Bedrock (opcional) | mesmo modelo, autenticação por IAM | conteúdo do documento | permanece na conta/região (**confirmar com compliance**) |
| AWS S3, SQS, Lambda, KMS, CloudWatch (opcionais) | execução em nuvem | documentos e saídas | ver [aws.md](../c_architecture/aws.md) |
| MySQL 8.4 (container do compose) | projeção consultável e login do console | cópia dos registros (já públicos para o operador) e usuários | só na rede interna do compose; senhas aleatórias no `.env` |

## 5. O que *não* usamos e por quê
LangChain/LangGraph (fluxo conhecido), banco vetorial/RAG (base de 12 linhas), biblioteca de componentes/CSS de terceiros (CSP e
identidade trocável), skills de terceiros (sem aprovação). Docker Compose e banco SQL **são usados** (MySQL 8.4 como projeção
consultável e para o login do console; SQLAlchemy Core, `pymysql`), mas o banco **não** é a fonte da verdade. Ver a tabela
completa em [decisões](../g_decisions/decisions.md#7-o-que-decidi-não-fazer-e-por-quê).
