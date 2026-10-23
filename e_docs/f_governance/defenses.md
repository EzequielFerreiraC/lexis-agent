# Catálogo de defesas

Tudo que o Lexis faz para não aprovar um dado errado, não vazar nada e não ser usado contra quem o opera. Cada defesa tem **ameaça**, **mecanismo**, **onde está** e **como é testada**. Para o mapeamento a referenciais (OWASP LLM Top 10, NIST AI RMF), retenção e acesso: [security_and_audit.md](security_and_audit.md). Para o *porquê* de cada escolha: [decisões](../g_decisions/decisions.md).

**Como ler.** O sistema não confia em uma barreira só. A ordem abaixo segue o caminho do documento (veja o [pipeline](../c_architecture/pipeline.md)); cada grupo é uma camada da defesa em profundidade. Onde a defesa tem limite conhecido, ele está dito na última coluna ou na seção **Limites** no fim.

Código em `a_src/b_backend/lexis/`; testes em `b_tests/` (`a_unit`, `b_integration`, `c_security`).

---

## 1. Entrada: o PDF é hostil até prova em contrário

| # | Ameaça | Defesa | Onde | Teste |
|---|---|---|---|---|
| D-01 | PDF gigante (custo, travar) | Limites de 20 MB e 20 páginas, checados **antes** de qualquer chamada externa. Na AWS, o `ContentLength` é conferido **antes de ler** o corpo | `b_ingestion/pdf.py`, `g_adapters/s3_storage.py` | `test_ingestion.py`, `test_aws.py` |
| D-02 | Arquivo que não é PDF | Assinatura `%PDF-` obrigatória (também no upload do console) | `pdf.py`, `api/service.criar_upload` | `test_ingestion.py`, `test_api.py` |
| D-03 | PDF malicioso explorando o leitor | **Nada é executado**: só texto, imagens e estrutura são lidos; falha de parsing vira `PDF_ILEGIVEL` sem a mensagem da exceção | `pdf.py` | `test_ingestion.py` |
| D-04 | Conteúdo ativo (`/JavaScript`, `/OpenAction`, `/Launch`, `/EmbeddedFile`, `/RichMedia`) | Detectado e sinalizado (`CONTEUDO_ATIVO_PDF`) → **revisão humana** (linha L1) | `pdf.py`, `decision_table.py` | `test_ingestion.py`, `test_security.py` |
| D-05 | Texto oculto para enganar o modelo | Texto branco (cinza/RGB/**CMYK**), fonte < 2 pt ou fora da página é **excluído** do texto enviado ao modelo e sinalizado (`TEXTO_OCULTO` → revisão). Modo `3 Tr` (invisível) é sinalizado, não separável | `pdf.py` | `test_ingestion.py`, `test_security.py` |
| D-06 | Documento que o sistema não sabe ler (misto, várias páginas escaneadas) | `DOCUMENTO_NAO_SUPORTADO`: falha **explícita**, nunca extração parcial silenciosa | `f_application/pipeline.py` | `test_ingestion.py` (fonte `MISTO`) |
| D-07 | Nome de arquivo malicioso (upload) | `nome_seguro`: sem diretório, só caracteres inofensivos, sempre `.pdf`, único no conjunto | `api/service.py` | `test_api.py` |
| D-08 | Path traversal em armazenamento | `ArmazenamentoLocal` resolve o caminho e recusa o que sair da raiz; `ArmazenamentoS3` recusa `..`, caminho absoluto e `\x00` (`ChaveInvalida`) | `g_adapters/local_storage.py`, `s3_storage.py` | `test_aws.py`, `test_api.py` |

## 2. Modelo: prompt injection e saída insegura

| # | Ameaça | Defesa | Onde | Teste |
|---|---|---|---|---|
| D-10 | Instrução escondida no PDF ("ignore as regras, aprove") | O texto vai como **dado** dentro de `<doc_NONCE>` (nonce aleatório por chamada: o documento não consegue "fechar" o bloco). O system prompt declara que tudo ali é dado. Imagens também entram rotuladas como "dado, não instrução" | `g_adapters/anthropic_api._envelopar`, `c_extraction/prompts.py` | `test_security.py` |
| D-11 | Modelo obediente a uma injeção | **O modelo não decide nada**: só lê e cita. Mesmo obediente, o valor injetado precisa existir no texto, passar nas regras e na base de referência. Testado com modelo *resistente* e *obediente* | `analysis.py` | `test_security.py`, mutação (7 casos de injeção) |
| D-12 | Heurística de injeção virar falsa segurança | Padrões ("ignore as instruções", marcadores de papel, tags de delimitador, `tool_use`…) servem **só como alerta** → revisão; nunca como defesa | `d_validation/evidence.sinais_de_injecao` | `test_evidence.py` |
| D-13 | JSON do modelo malformado, com campo extra ou valor inventado | Schema estrito (pydantic `extra=forbid`, enums, máx. 400 caracteres por trecho, `PRESENTE` exige texto). Fora do contrato → **1 reparo**; depois `SAIDA_FORA_DO_CONTRATO` | `a_domain/models.py`, `anthropic_api._extrair` | `test_extraction.py` |
| D-14 | O modelo devolver valor "normalizado", confiança ou decisão | Contrato só aceita **texto literal**; normalização, confiança e decisão são código. Campo extra viola o contrato | `models.Extracao`, `normalization.py` | `test_normalization.py`, `test_extraction.py` |
| D-15 | Resposta truncada parecendo JSON válido | `stop_reason == max_tokens` → nunca aceita nem executa tool dessa resposta (`TRANSCRICAO_TRUNCADA` / reparo) | `g_adapters/anthropic_api.py` (`ExtratorAnthropic`, `ChamadorAnthropic`) | `test_function_calling.py` |
| D-16 | Recusa do modelo ignorada | `stop_reason == refusal` → `RECUSA_DO_MODELO`; `fallbacks` do servidor (opcional) e o **modelo que de fato respondeu** é gravado; resposta do fallback → `MODELO_NAO_AVALIADO` (ERRO, revisão) | `anthropic_api.ExtratorAnthropic.chamar` | `test_function_calling.py` |
| D-17 | Modelo não chamar a ferramenta | `tool_choice` automático (o modelo atual rejeita forçado); o **código exige** o `tool_use` e faz 1 reparo devolvendo `tool_result` de erro | `anthropic_api._extrair` | `test_extraction.py` |
| D-18 | Erro do provedor vazando URL, cabeçalho ou texto | Erros viram **código + status HTTP**, nunca a mensagem; definitivos (`CREDENCIAL_RECUSADA`, `REQUISICAO_REJEITADA`) separados dos transitórios (`FALHA_PROVEDOR`) | `anthropic_api._codigo_do_erro` | `test_function_calling.py` |

## 3. Verificação: "plausível, mas errado" não passa

| # | Ameaça | Defesa | Onde | Teste |
|---|---|---|---|---|
| D-20 | **Valor alucinado ou dígito trocado** (o principal risco) | **Evidência literal**: o trecho citado precisa existir na página (forma canônica), sem começar nem terminar no meio de um número (citação truncada não vale). Senão o campo vira `INCERTO` e o registro vai à revisão | `d_validation/evidence.verificar_citacao` | `test_evidence.py`, mutação |
| D-21 | Valor mal interpretado | Normalização determinística; ambiguidade (duas datas, dois números) → `INCERTO` em vez de escolher | `normalization.py` | `test_normalization.py` |
| D-22 | Confundir "não existe", "faltou" e "vem depois" | `NAO_APLICAVEL` ≠ `AUSENTE` ≠ `PENDENTE`, definidos por tipo em `rules.json`. Grupamento não "perde" data de pagamento; "a definir" nunca é inventado | `a_domain/rules.json`, `analysis.py` | `test_pipeline.py` |
| D-23 | Classificar o tipo errado (muda o tratamento tributário) | **Segunda opinião** determinística por sinais ponderados por zona; divergência com o modelo = ERRO | `d_validation/classification.py` | `test_classification.py` |
| D-24 | Título enganoso ("Dividendos" sobre um JCP) | Prevalece o corpo; o conflito vai **sempre** ao humano (L3), por risco tributário. Política configurável | `classification.py`, `decision_table.py` | `test_classification.py`, `test_decision.py` |
| D-25 | Identificador visível no texto e omitido na extração | `IDENTIFICADOR_NAO_EXTRAIDO` | `evidence.varrer_identificadores` | `test_evidence.py` |
| D-26 | Erro correlacionado no scan (duas leituras do **mesmo** modelo) | Leituras A e B por métodos diferentes devem concordar campo a campo; OCR local como terceiro leitor independente; confiança limitada a MÉDIA; **sem OCR independente, scan sempre vai ao humano** (L5) | `analysis.py`, `g_adapters/tesseract_ocr.py`, `decision_table.py` | `test_pipeline.py`, mutação (scan) |
| D-27 | Mesmo evento em PDFs diferentes (lançamento em dobro) | `DUPLICATA_POSSIVEL` (ERRO) por ISIN + tipo + data com: os dois vão à revisão | `f_application/batch.py` | `test_pipeline.py` |

## 4. Validação por tools: o modelo não valida nada

| # | Ameaça | Defesa | Onde | Teste |
|---|---|---|---|---|
| D-30 | Agência excessiva (modelo chamando o que não deve) | **Allow-list fechada de 4 tools**, todas somente leitura. Nome fora da lista → `FORA_DA_ALLOW_LIST`; fora do tipo → `NAO_APLICAVEL_AO_TIPO`; repetida → `DUPLICADA` | `d_validation/tools.py` | `test_tools.py` |
| D-31 | Modelo "validar" valores inventados | Argumentos precisam ser **idênticos aos campos extraídos**. Divergência volta como erro apontando o **nome** do campo, nunca o valor certo | `tools.orquestrar.atender` | `test_tools.py`, `test_function_calling.py` |
| D-32 | O parecer do modelo contaminar a decisão | **Veredito = resultado da tool**, executada pelo código. O parecer é texto informativo e não entra em `regras` | `analysis._resumo_conversa` | `test_function_calling.py` |
| D-33 | Modelo pular uma tool | O orquestrador executa as obrigatórias faltantes (origem `ORQUESTRADOR`). Falha do provedor na conversa **não** derruba a validação | `tools.orquestrar` | `test_function_calling.py` |
| D-34 | Loop infinito de tools | Máximo de 4 turnos (`LIMITE_DE_TURNOS`) | `anthropic_api.MAX_TURNOS` | `test_function_calling.py` |
| D-35 | Valores do registro fecharem o bloco de dados | O registro entra entre `<registro_NONCE>` | `anthropic_api.ChamadorAnthropic` | `test_function_calling.py` |
| D-36 | Base de referência ser usada para "corrigir" | Match **exato** por ISIN/ticker/CNPJ; nome parecido gera só *sugestão para o operador*, nunca confirma. CNPJ com várias classes confirma o emissor, não a classe. O modelo nunca preenche o que a base não tem | `d_validation/reference_base.py` | `test_reference_base.py` |
| D-37 | Líquido errado por alíquota presumida | Alíquota **vem do aviso**; sem alíquota, a regra é `NAO_APLICAVEL`. Tolerância de 0,5 unidade da última casa (1 unidade deixava passar troca do último dígito, achado da mutação) | `coherence.checar_tributacao` | `test_coherence.py`, mutação |
| D-38 | Datas incoerentes | `ex > com`, `pagamento ≥ com/ex`, `crédito ≥ com`; ex = próximo dia útil pelo **calendário B3** (2024–2030; fora disso só fins de semana, e o detalhe da regra diz isso); datas a mais de 550 dias da aprovação sugerem erro de ano | `coherence.py`, `market_calendar.py` | `test_coherence.py`, `test_market_calendar.py` |
| D-39 | Dividendo disfarçado de JCP (ou vice-versa) | `TRIB_DIVIDENDO_COM_RETENCAO`; proporção coerente com o tipo (`PROP_SENTIDO_INCOMPATIVEL`, `PROP_PERCENTUAL_DIVERGE`) | `coherence.py` | `test_coherence.py` |
| D-40 | Replay "mentir" sobre as tools | Na reprodução, cada pedido gravado é **reexecutado** e comparado; a gravação só vale se `pedido_sha` (registro + tools + prompt) for igual | `c_extraction/recordings.ChamadorComCache` | `test_function_calling.py` |

## 5. Decisão: nunca aprovar no escuro

| # | Ameaça | Defesa | Onde | Teste |
|---|---|---|---|---|
| D-50 | Decisão inexplicável | **Tabela de decisão** de 7 linhas, a primeira verdadeira vence; a linha que decidiu vai no registro. Uma asserção de teste por linha | `e_decision/decision_table.py` | `test_decision.py` |
| D-51 | Limiar ajustado ao lote de teste | Campo crítico ≥ MÉDIA, fixado **a priori**; recalibração só com vereditos reais (auditoria amostral) | `rules.json` (`politica`) | `test_decision.py` |
| D-52 | Falsa precisão | Confiança em **níveis discretos com motivos**, não nota numérica (não há base rotulada para calibrar) | `e_decision/confidence.py` | `test_decision.py` |
| D-53 | Falha virar dado parcial | `FALHA_PROCESSAMENTO` é um registro válido e explícito; nunca reaproveitado | `pipeline.registro_falha`, `batch.reutilizavel` | `test_pipeline.py`, `test_code_review.py` |
| D-54 | Operador sem saber o que fazer | `fichas_conferencia` (o que conferir, onde, ação) e `para_aprovar` (o que destrava a aprovação) | `checklists.py`, `decision_table.para_aprovar` | `test_decision.py` |

## 6. Consumo, resiliência e idempotência

| # | Ameaça | Defesa | Onde | Teste |
|---|---|---|---|---|
| D-60 | Custo/latência ilimitados | `max_tokens`, timeout (padrão 120 s), retries limitados do SDK, **orçamento de tokens por lote/invocação** (`ORCAMENTO_EXCEDIDO`) | `c_extraction/config.py`, `g_adapters/anthropic_api.py` | `test_resilience_and_costs.py` |
| D-61 | Provedor fora derrubando o lote inteiro | **Circuit breaker**: 3 falhas seguidas do provedor, ou credencial recusada, ou orçamento estourado param as chamadas. O que já estava pronto continua valendo e **nada bom é sobrescrito** | `f_application/batch.py` | `test_resilience_and_costs.py` |
| D-62 | Um documento ruim derrubar o lote | Defesa final: qualquer exceção vira `ERRO_INESPERADO` com *onde* (arquivo:linha), nunca a mensagem | `pipeline.processar_conteudo` | `test_code_review.py` |
| D-63 | Falha transitória virar resultado final (fila) | Com `propagar_transitorios`, a falha é devolvida à fila → **DLQ**; `batchItemFailures` no SQS | `pipeline.py`, `aws_lambda.py` | `test_aws.py`, `test_code_review.py` |
| D-64 | Reprocessamento e custo duplicado | **Idempotência por SHA-256 + versões** (pipeline, regras, prompt, base, schema): `REUTILIZADO`. Duplicata no lote: `DUPLICADO_NO_LOTE` | `batch.reutilizavel` | `test_pipeline.py` |
| D-65 | Orçamento acumulando entre invocações quentes | `Contexto.reiniciar()` zera o orçamento por lote/invocação | `pipeline.py`, `aws_lambda.handler` | `test_code_review.py` |
| D-66 | Custo inventado | Estimativa por tabela de preços públicos, marcada como estimativa; modelo sem preço ⇒ `null` | `c_extraction/costs.py` | `test_resilience_and_costs.py` |

## 7. Reprodutibilidade e integridade

| # | Ameaça | Defesa | Onde | Teste |
|---|---|---|---|---|
| D-70 | Não conseguir reproduzir um resultado (modelo não determinístico) | **Gravações** das respostas reais por SHA-256 do PDF; `replay` reproduz sem rede nem chave. Não há `temperature` (modelos atuais rejeitam): a reprodutibilidade vem das gravações | `c_extraction/recordings.py` | `test_extraction.py` |
| D-71 | Gravação de outra versão enganar o replay | `FIXTURE_DESATUALIZADA` (SHA do PDF não confere), `GRAVACAO_PROMPT_DIVERGENTE` (prompt mudou), `GRAVACAO_DESATUALIZADA` (tools mudaram) | `recordings.py` | `test_extraction.py` |
| D-72 | OCR do ambiente mudar o resultado | OCR é **etapa gravada** (`ocr.json`); o replay nunca usa o Tesseract da máquina | `recordings.ler_ocr` | `test_pipeline.py` |
| D-73 | Não saber o que produziu um registro | Cada JSON carrega versões: código, regras+hash, prompt, modelo, base, schema, tempos, tokens, tentativas | `pipeline.versoes` | `test_pipeline.py` |
| D-74 | Adulteração da trilha | **Cadeia de hashes**: cada linha de `auditoria.jsonl`/`revisoes.jsonl` carrega `hash_anterior` e `hash`. Alterar, remover, inserir ou reordenar quebra a cadeia | `a_domain/hash_chain.py`, `g_adapters/local_trail.py` | `test_hash_chain.py` |
| D-75 | Adulteração de um registro depois de gravado | Evento `registros_publicados` sela o SHA-256 de cada JSON; `lexis auditar` confere registro alterado, ausente ou a mais | `f_application/integrity.py` | `test_integrity.py` |
| D-76 | Decisão humana "migrar" para outro conteúdo | A decisão fica presa ao SHA-256 do registro revisado; `lexis auditar` confere também o evento `revisao_humana` na trilha (e vice-versa) | `integrity._verificar_revisoes` | `test_integrity.py` |
| D-77 | Contrato de saída divergir do código | JSON Schema e OpenAPI publicados; teste falha se o modelo mudar sem regenerar (`lexis contratos`) | `h_interfaces/contracts.py`, `e_docs/e_contracts/` | `test_contract.py` |
| D-78 | Barreira do código enfraquecer sem ninguém ver | **Avaliação por mutação**: injeta defeitos controlados (derivados do próprio documento e da base) e mede se deixam de ser aprovados. O **CI falha** se algum passar como `APROVADO_AUTO` | `i_assessment/evaluation.py`, `ci.yml` | `test_evaluation.py` |
| D-79 | Auditoria do lote entregue | O CI roda `lexis auditar` sobre o lote versionado | `.github/workflows/ci.yml` | CI |

## 8. Dados, segredos e privacidade

| # | Ameaça | Defesa | Onde | Teste |
|---|---|---|---|---|
| D-80 | Texto do documento em log | Logs e `auditoria.jsonl` só com **ids, hashes, códigos e contagens** | `batch._log` (`logging`), `log_trail.py` | `test_security.py`, `test_aws.py` |
| D-81 | Mensagem de exceção vazando dado | Diagnóstico de erro inesperado traz *onde* (arquivo:linha:função) e o **tipo** da exceção, nunca a mensagem | `pipeline.onde_falhou` | `test_code_review.py` |
| D-82 | Chave de API vazando | Só por variável de ambiente (`.env` no `.gitignore`, fora da imagem pelo `.dockerignore`, `.env.example` sem valor); `api_key` fora do `repr`; na AWS, Secrets Manager. `gitleaks` no CI | `c_extraction/config.py`, `ci.yml` | CI, `test_extraction.py` |
| D-83 | Chave digitada no console vazar | Fica **só na memória** do servidor (nunca em disco, log, auditoria ou resposta; só os 4 últimos caracteres voltam); formato validado com mensagem fixa que nunca ecoa o digitado | `api/service.definir_chave` | `test_api.py` |
| D-84 | Dado pessoal sem finalidade | Nomes de signatários **não são extraídos**. O único dado pessoal gravado é o nome do operador que decide uma revisão (responsabilização), fora da trilha | prompt, `service.revisar` | revisão do prompt e do esquema de dados |
| D-85 | URL do banco (com senha) em erro | Só o **tipo** da exceção é mostrado | `cli._engine`, `service._projetar` | `test_sql.py` |
| D-86 | Troca de modelo sem evidência | O console mostra o modelo **só para leitura**; vem de `LEXIS_MODEL` (config de deploy), porque gravações e mutação só valem para o modelo avaliado | `api/service.configuracao` | `test_api.py` |
| D-87 | Gasto inesperado no console | Modo **Ao vivo** só habilita com chave e exige confirmação explícita (diálogo + `confirmar_live` na API) | `service.iniciar_execucao` | `test_api.py`, `flow.spec.ts` |

## 9. Console web e API

O servidor roda na máquina do operador, executa código Python que lê PDFs não confiáveis e pode gastar dinheiro com o modelo. Qualquer página aberta no navegador consegue enviar requisições para `localhost`, e DNS rebinding aponta um nome externo para `127.0.0.1`.

| # | Ameaça | Defesa | Onde | Teste |
|---|---|---|---|---|
| D-90 | Exposição na rede | Só **loopback**: `--host` não-loopback é recusado. No container, `serve --container` escuta na interface do container (**recusado fora de um container**) e o compose publica a porta só em `127.0.0.1` | `h_interfaces/cli._serve`, `api/security.py`, `docker-compose.yml` | `test_api.py` |
| D-91 | DNS rebinding | Cabeçalho `Host` conferido contra `127.0.0.1`/`localhost`/`[::1]` em toda requisição | `api/security.py` | `test_api.py` |
| D-92 | CSRF / outro site ou processo local chamando a API | **Token aleatório por subida** (256 bits) em `Authorization: Bearer`, conferido **antes de ler o corpo**, comparação em tempo constante. Sem cookie para esse token, logo sem CSRF | `api/security.py` | `test_api.py` |
| D-93 | Token vazando em URL, log ou histórico | Vai no **fragmento** (`#token=`, nunca enviado ao servidor nem registrado), é movido para `sessionStorage` e removido da barra de endereço; nunca em query string nem `localStorage` | `a_frontend/src/auth/token.ts`, `cli._serve` | `token.test.ts`, `flow.spec.ts` |
| D-94 | XSS / HTML vindo do documento | Texto de PDF só é renderizado **como texto** (React); `dangerouslySetInnerHTML` é **proibido por lint**; sem `<iframe>`/`<embed>` do PDF | `a_frontend/eslint.config.js` | `npm run lint` |
| D-95 | Script ou estilo injetado | **CSP** `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`; mais `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, COOP/CORP `same-origin`, `Permissions-Policy`, `Cache-Control: no-store` na API. Sem CSS/JS injetado em tempo de execução (biblioteca que injeta `<style>` foi descartada) | `api/security.CABECALHOS_BASE`, `flow.spec.ts` | `test_api.py`, e2e (checa violações de CSP) |
| D-96 | PDF aberto no navegador | O servidor **renderiza a página em PNG**; o front busca com o token e exibe como `data:`. O navegador nunca recebe nem abre o PDF | `api/app.imagem` | `test_api.py` |
| D-97 | Caminho vindo do cliente | O navegador **nunca envia caminho**: nomes são validados contra listas do servidor; ids são `[0-9a-f]{12}` ou `report_yymmdd_hhmm`; relatórios só de uma **lista fechada**; o front estático é resolvido **dentro** da pasta do build | `api/service.py`, `api/app.front` | `test_api.py` |
| D-98 | Upload abusivo | Só PDF (`%PDF-`), 20 MB × 20 arquivos; `Content-Length` conferido **antes de ler o corpo**; sem `Content-Length` confiável, recusa (413); leitura nunca passa de `MAX_BYTES + 1` | `api/security._corpo_grande_demais`, `app.enviar` | `test_api.py` |
| D-99 | Documentação pública da API | `docs_url`, `redoc_url` e `openapi_url` desligados; o contrato é exportado por script | `api/app.criar_app` | `test_api.py` |
| D-100 | Execução sobrescrever material de referência | Cada execução grava na **própria pasta**; `c_replay/` é só leitura no console (`ArmazenamentoEmCamadas`) | `service._contexto`, `docker-compose.yml` | `test_api.py` |
| D-101 | Servidor reiniciado no meio | Execuções interrompidas aparecem como **falha**, nada é retomado em silêncio | `service._carregar_do_disco` | `test_api.py` |
| D-102 | UI inventando destaque | Campo sem posição (scan) diz "sem posição na página", **não** ganha destaque | `HighlightedPage.tsx` | `app.test.tsx`, `flow.spec.ts` |

## 10. Identidade, sessão e decisão humana (com banco)

| # | Ameaça | Defesa | Onde | Teste |
|---|---|---|---|---|
| D-110 | Senha vazada do banco | **scrypt** (N=2¹⁵, r=8, p=1, ~32 MiB) com **sal** aleatório por usuário; só `scrypt$…` é guardado; comparação em tempo constante | `g_adapters/sql_users.py` | `test_sql.py` |
| D-111 | Senha fraca | Mínimo de 12 caracteres e sem o login dentro; login validado por regex | `sql_users.validar_senha`, `criar_usuario` | `test_sql.py` |
| D-112 | Enumerar logins | Mesma resposta para login inexistente e senha errada, **e o mesmo custo de scrypt** (sal fictício) | `sql_users.autenticar`, `service.entrar` | `test_api_login.py` |
| D-113 | Força bruta | 5 erros do mesmo login em 15 min bloqueiam o login (HTTP 429). O contador fica **em memória**: zera ao reiniciar o servidor | `service.entrar` | `test_api_login.py` |
| D-114 | Roubo de sessão pela tabela | Token de sessão de 256 bits só existe no **cookie**; o banco guarda o **SHA-256**. Expira em 8 h; limpeza oportunista | `sql_users.abrir_sessao` | `test_sql.py` |
| D-115 | Cookie roubado por script ou enviado por outro site | `HttpOnly`, `SameSite=Strict`, restrito a `/api`; o token Bearer **continua exigido** (CSRF precisaria dos dois) | `api/app.entrar` | `test_api_login.py` |
| D-116 | Identidade falsa na trilha de revisão | Com login, o operador é o **usuário autenticado** (o nome digitado é ignorado). Sem banco, o login não existe e o nome é declarado (limite documentado) | `service.revisar` | `test_api_login.py` |
| D-117 | Aprovar sem olhar | Para aprovar é preciso **reconhecer todos os motivos** (o servidor confere de novo), justificar (≥ 10 caracteres) e confirmar num diálogo; só documentos em `REVISAO_HUMANA` recebem decisão | `service.revisar`, `ReviewPanel.tsx` | `test_api.py`, `app.test.tsx` |
| D-118 | Decisão humana sobrescrever o automático | O **registro do pipeline nunca muda**: a decisão fica ao lado, presa ao SHA-256 do registro, em `execucao.json`, `revisoes.jsonl` e (só códigos e hashes) `auditoria.jsonl`. Nome e justificativa **nunca** vão para a trilha | `service.revisar` | `test_api.py`, `test_integrity.py` |
| D-119 | Decisão duplicada ou fora de ordem | Uma decisão por documento e execução (a segunda recebe **409**); refazer exige nova execução; execução ainda em curso → 409 | `service.revisar`, `sql_schema.revisao` (`documento_id` único) | `test_api.py`, `test_sql.py` |

## 11. Banco de dados

| # | Ameaça | Defesa | Onde | Teste |
|---|---|---|---|---|
| D-120 | SQL injection | **Toda consulta é parametrizada** (SQLAlchemy Core); nenhum texto de documento entra em SQL montado à mão | `g_adapters/sql_*.py` | `test_sql.py` (`'); DROP TABLE` gravado literalmente) |
| D-121 | Banco divergir do registro auditado | O banco é **projeção reconstruível**; cada `documento` guarda o `sha256_registro` do JSON de origem; reimportar é idempotente | `sql_store.projetar_execucao` | `test_sql.py` |
| D-122 | Falha do banco desfazer uma execução válida | Falha na projeção só avisa (sem mensagem); a execução e a revisão já estão seladas; `lexis db importar` reprojeta | `service._projetar` | sem teste dedicado |
| D-123 | Dado inválido no banco | `CHECK` nas decisões e vereditos, chaves estrangeiras, índices nas consultas reais | `sql_schema.py` | `test_sql.py` |
| D-124 | Veredito de auditoria reescrito | O veredito **não se reescreve** (`UPDATE … WHERE veredito IS NULL`); `ERRADO` exige campo e valor certo | `sql_store.registrar_veredito` | `test_sql.py` |
| D-125 | Banco exposto | MySQL **sem porta publicada** (só a rede interna do compose); usuário da aplicação só no banco `lexis`; senhas **aleatórias** no `.env` (permissão 600); healthcheck sem credencial | `docker-compose.yml`, `d_scripts/_common.sh` | CI (compose) |
| D-126 | Falso aprovado automático invisível | **Auditoria amostral estratificada** dos `APROVADO_AUTO` (às cegas, sorteio reproduzível por semente) com taxa de erro e **intervalo de Wilson de 95%**: a métrica diz o quanto ainda não se sabe | `sql_store.sortear_auditoria`, `metricas` | `test_sql.py` |
| D-127 | Projeções concorrentes da mesma execução (fim do lote e revisão do operador) se atropelarem e a revisão ficar fora do banco | Projeções serializadas por uma trava no serviço; a última lê `revisoes.jsonl` já dentro da trava. Achado na verificação de 2026-10-23 (falhava em ~1 de 2 rodadas do teste) | `api/service._projetar` | `test_api_login.py` |

## 12. AWS (preparado, não implantado)

| # | Ameaça | Defesa | Onde | Teste |
|---|---|---|---|---|
| D-130 | *Confused deputy* | Só processa o **bucket configurado**; evento de outro bucket é rejeitado e registrado | `aws_lambda.handler` | `test_aws.py` |
| D-131 | Laço de eventos | `LEXIS_BUCKET_SAIDA` precisa ser **diferente** de `LEXIS_BUCKET_ENTRADA` | `aws_lambda.handler` | `test_aws.py` |
| D-132 | Entrada inesperada | Só `.pdf`; objetos > 20 MB recusados antes do corpo | `aws_lambda.py`, `s3_storage.py` | `test_aws.py` |
| D-133 | Dado em repouso | SSE-KMS opcional (`aws:kms`), Block Public Access, versionamento; IAM de menor privilégio por prefixo; VPC endpoints | [aws.md](../c_architecture/aws.md) | política (sem IaC) |
| D-134 | Trilha adulterada por quem reescreve a pasta | Cadeia de hashes **detecta**; **impedir** é papel de S3 com Object Lock (Firehose) | aws.md | política |
| D-135 | Chave de API na função | Secrets Manager (ARN) ou **Bedrock com IAM**, sem chave | `aws_lambda._fabrica_extrator` | sem teste dedicado (Bedrock e Secrets Manager não são exercitados) |

## 13. Container e cadeia de suprimentos

| # | Ameaça | Defesa | Onde | Teste |
|---|---|---|---|---|
| D-140 | Container comprometido ganhando privilégio | Usuário **sem root** (uid/gid do host), sistema de arquivos **somente leitura** (`tmpfs` em `/tmp`), `cap_drop: ALL` | `docker-compose.yml`, `Dockerfile` | CI (build) |
| D-141 | Segredo na imagem | `.env` nunca entra na imagem (`.dockerignore`), é lido em tempo de execução | `.dockerignore`, `docker-compose.yml` | revisão |
| D-142 | Dependência adulterada ou vulnerável | `requirements*.txt` com **hashes** (`--require-hashes`), `npm ci`, `pip-audit`, `npm audit`, `gitleaks` | `ci.yml` | CI |
| D-143 | Regressão de qualidade | `ruff` (inclui regras de segurança `S`), `mypy --strict`, `tsc --strict`, ESLint (`typescript-eslint` strict + `jsx-a11y`), Prettier; CI em Python, front, Docker e e2e | `pyproject.toml`, `ci.yml` | CI |
| D-144 | Contrato da API defasado no front | Tipos TS gerados do OpenAPI; CI roda `gen:api` e falha em diferença | `ci.yml` | CI |
| D-145 | Acessibilidade e CSP quebrando sem aviso | `axe-core` em cada tela e aba (Vitest) e no e2e (com contraste); e2e falha com violação de CSP | `a_frontend/e2e/flow.spec.ts` | e2e |
| D-146 | Adaptador (rede, OCR, nuvem, banco, ambiente) vazar para o núcleo e quebrar a arquitetura hexagonal sem ninguém ver | Teste lê o código (AST) e falha se `a_`–`f_` importar biblioteca de I/O, adaptador ou camada acima, abrir arquivo, imprimir ou ler `os.environ` | `b_tests/a_unit/test_architecture.py` | o próprio teste (conferido com violação injetada) |

---

## Limites conhecidos (o que **não** está defendido)

Honestidade sobre o que as defesas acima não cobrem.

| Limite | Por quê / mitigação |
|---|---|
| **Valor plausível injetado e citado no próprio documento**, sem outra fonte para contradizê-lo (ex.: um bruto falso num aviso sem líquido) | Único caso da mutação que passa como aprovado (marcado `detectavel: false`). Mitigação em escala: conferência com fontes externas (custódia, B3/CVM) e auditoria amostral |
| **Data ou valor real de outro campo** (ex.: a data de aprovação citada como data com) | A evidência confere que o trecho existe, não que pertence ao rótulo; só é pego se uma regra de coerência o reprovar. Na mutação, 5 casos `detectavel: false`. Mitigação: o modelo citar o rótulo junto e o código conferir a proximidade |
| **Aviso com mais de um evento ou classe** (ON e PN com valores diferentes; dividendo e JCP juntos) | O contrato tem um evento por documento; `IDENTIFICADOR_NAO_EXTRAIDO` é só AVISO. Mitigação: bloquear quando o texto tiver mais de um ISIN/valor por ação e, depois, uma lista de eventos no contrato |
| **Duplicata entre execuções diferentes** | Só a duplicata dentro do lote bloqueia; entre execuções, é consulta no banco |
| **Texto coberto por um retângulo da cor do fundo** | Sem a ordem de desenho, testar isso gera falso positivo em tabelas legítimas. Mitigação: comparar texto nativo com OCR da página renderizada |
| **Modo `3 Tr`** | Detectado, mas o texto não é separável do visível |
| **Erro sistemático compartilhado** por leituras do mesmo modelo (scan) | Por isso o OCR independente e a regra L5; ainda assim, a concordância entre leituras é evidência fraca |
| **Cadeia de hashes não impede adulteração** | Quem reescreve a pasta inteira recalcula os hashes. Impedir exige armazenamento imutável (Object Lock) |
| **Modelo não determinístico** | As gravações fixam **uma** amostra; regravar pode mudar o resultado (nas 4 execuções completas, toda diferença foi uma revisão a mais, nunca uma aprovação indevida) |
| **Bloqueio de força bruta em memória** | Reiniciar o servidor zera o contador; não há bloqueio por IP. Aceitável para console local; em produção, viria do provedor de identidade |
| **Login local não é SSO** | Sem MFA, papéis ou integração com identidade corporativa; sem banco, o nome do operador é declarado, não autenticado |
| **Dígito verificador de ISIN/CNPJ não é validado** | A base sintética falharia (10 de 12 ISINs, 11 de 12 CNPJs). Valida-se formato + igualdade com a base |
| **Calendário B3** cobre 2024–2030 e feriados regulares | Não foi conferido contra o oficial; feriado extraordinário pode gerar aviso incorreto (por isso é AVISO, não ERRO) |
| **Concorrência e carga** | O processamento é sequencial por processo; idempotência concorrente (escrita condicional no DynamoDB) **não implementada** |
| **AWS não implantada** | Testada só com clientes falsos; sem IaC |
| **Acessibilidade** | Testado: axe em cada tela e no e2e (com contraste) e navegação só por teclado com foco visível (e2e). **Não** testado: leitor de tela de verdade |
| **Egress de dados** | O conteúdo do documento vai à API do provedor. O lote é sintético; em produção exige DPA/zero-retention, região e classificação do dado |
