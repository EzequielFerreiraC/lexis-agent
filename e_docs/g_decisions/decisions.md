# Decisões de engenharia

Cada decisão tem **o que foi escolhido**, **por quê**, **o que ficou de fora** e **o que muda com milhares de documentos** (o lote entregue tem 8: ele serve para provar o desenho, não para medir produção). Para as defesas que decorrem destas decisões: [defenses.md](../f_governance/defenses.md). Para o contexto histórico da análise inicial: [plan.md](../b_plan/plan.md).

Índice: [1. Desenho](#1-desenho-do-sistema) · [2. Extração e modelo](#2-extração-e-modelo) · [3. Validação e decisão](#3-validação-e-decisão) · [4. Scan](#4-scan) · [5. Auditoria e dados](#5-auditoria-e-dados) · [6. Console e segurança](#6-console-e-segurança) · [7. O que decidi não fazer](#7-o-que-decidi-não-fazer-e-por-quê) · [8. Premissas](#8-premissas) · [9. Em escala](#9-em-escala-milhares-de-documentos)

---

## 1. Desenho do sistema

### DEC-01 · Pipeline híbrido, não agente autônomo
- **Decisão:** o fluxo é conhecido (ler → verificar → validar → decidir), então é um pipeline controlado. O modelo entra onde há linguagem e visão; o código decide.
- **Alternativas:** (A) só regras/regex: quebra com layout novo e não lê scan; (B) um prompt que devolve JSON: aceita "plausível, mas errado" e não é auditável; (D) agente ReAct: não determinístico, custo e latência variáveis, difícil de defender; (E) multiagente/LangGraph: complexidade sem ganho.
- **Em escala:** a previsibilidade é o que permite estimar custo por documento e medir taxa de erro. Autonomia tornaria ambas instáveis.
- **Revisitar se:** surgirem tarefas abertas, sem fluxo fixo.

### DEC-02 · Arquitetura hexagonal: núcleo sem I/O, portas e adaptadores
- **Decisão:** o núcleo (`a_` a `f_`) não faz I/O. Armazenamento, trilha, provedor do modelo e OCR entram por portas (`ArmazenamentoObjetos`, `TrilhaAuditoria`, `Extrator`, `ChamadorDeTools`, `LeitorOCR`); os adaptadores ficam em `g_adapters/` (incluindo `anthropic_api.py`, `tesseract_ocr.py` e `ambiente.py`, que lê as variáveis de ambiente) e são ligados pelas entradas (`h_interfaces/`). O log do lote usa `logging`, e quem o liga a um destino é a entrada.
- **Verificado por teste:** `b_tests/a_unit/test_architecture.py` falha se o núcleo importar biblioteca de I/O, adaptador ou camada acima, abrir arquivo, imprimir ou ler o ambiente. Única exceção: `specs.py` lê `rules.json` (empacotado com o código) ao importar.
- **Histórico:** até a refatoração de 2026-10-23, o cliente Anthropic morava em `c_extraction/` e `d_validation/tools.py`, o OCR em `b_ingestion/`, e o `pipeline.py` instanciava o cliente por padrão. A mudança não alterou nenhum resultado: o replay do lote (com e sem OCR) e os 50 casos da mutação ficaram idênticos.
- **Fora do hexágono, de propósito:** o banco SQL não tem porta porque o núcleo não depende dele; é acionado pelas entradas (CLI e console).
- **Por quê:** o mesmo código roda no terminal, no console, em testes (memória + extrator falso) e numa Lambda. Trocar S3 por outro destino é um adaptador.
- **Em escala:** é o que permite levar o processamento para S3 → SQS → Lambda sem reescrever regra de negócio.

### DEC-03 · Regras como dado versionado (`rules.json`)
- **Decisão:** campos, matriz de aplicabilidade por tipo, severidade das regras e política (confiança mínima, teto do scan, tolerâncias) vivem em um JSON com versão e hash, gravados em cada saída.
- **Por quê:** o que é negócio não se espalha em constantes no código; mudar política é editar dado, com teste e mutação.
- **Em escala:** com muitos tipos de evento, a matriz continua sendo uma tabela revisável por quem conhece o negócio.

### DEC-04 · Camadas com prefixo de letra
- **Decisão:** pastas `a_` … `i_` na ordem de dependência, e as pastas de topo também (`a_src`, `b_tests`, `c_replay`, `d_scripts`, `e_docs`, `f_data`).
- **Por quê:** a ordem de leitura é a ordem de dependência; uma importação "para cima" salta aos olhos na revisão.

---

## 2. Extração e modelo

### DEC-05 · O modelo só lê e cita (texto literal + evidência)
- **Decisão:** para cada campo o modelo devolve o **trecho literal**, a página e a situação. Valor normalizado, confiança e decisão são do código; campo extra no JSON viola o contrato.
- **Por quê:** é o controle principal contra "resposta plausível, mas errada". Um dígito trocado ou um valor alucinado **não está no texto**, então o campo vira `INCERTO` e o registro vai à revisão.
- **Fronteira de número:** o trecho não pode começar nem terminar no meio de um número ("R$ 0,427" dentro de "R$ 0,4275" não vale), senão uma citação truncada mudaria o valor e ainda passaria.
- **Limite:** confere que o trecho existe, não que pertence ao rótulo do campo. Uma data real de outro campo (aprovação citada como data com) só é pega se alguma regra de coerência a reprovar. Ver [evaluation.md §4](../i_evaluation/evaluation.md).
- **Em escala:** é barato (uma busca de substring) e independe de calibração, então a garantia não degrada com o volume.

### DEC-06 · Modelo atual: sem `temperature`, `tool_choice` automático, `effort` explícito
- **Decisão:** o modelo atual rejeita `tool_choice` forçado e parâmetros de amostragem. O código **exige** o `tool_use` (1 reparo) e **não há `temperature`**; a reprodutibilidade vem das gravações. `effort=medium` e `fallbacks: default` (o modelo que de fato respondeu é gravado) ficam explícitos. Resposta vinda do fallback gera `MODELO_NAO_AVALIADO` (ERRO): a leitura é de um modelo que as gravações e a mutação não mediram, então vai ao humano. `refusal` → `RECUSA_DO_MODELO`; `max_tokens` → nunca executa tool de resposta truncada.
- **Em escala:** `effort` e modelo são os dois botões de custo/qualidade; ambos estão registrados em cada saída para comparar execuções.

### DEC-07 · `strict` só onde cabe
- **Decisão:** as 4 tools de validação usam `strict: true`. A tool de extração (≈ 20 objetos aninhados) **excede** a gramática do provedor ("compiled grammar is too large", HTTP 400) e fica sem strict, protegida por pydantic + 1 reparo.
- **Detalhe aprendido na execução real:** o strict limita parâmetros anuláveis (≤ 16) e opcionais (≤ 24); por isso os campos são `string` opcionais (ausente = omitido) e o registro é mostrado **na ordem do schema** (com outra ordem, o modelo omitiu `percentual_declarado` 7 vezes: no strict, passado um campo, ele não volta ao anterior).
- **Revisitar se:** o limite do provedor subir.

### DEC-08 · Gravações por SHA-256 e três modos (`replay`, `auto`, `live`)
- **Decisão:** cada resposta real do modelo é gravada em `c_replay/<sha256>/<etapa>.json`. `replay` (padrão) não usa rede nem chave; `auto` usa a gravação ou chama e grava; `live` sempre chama.
- **Por quê:** (1) avaliar sem custo e sem chave; (2) o mesmo lote dá o mesmo resultado em qualquer ambiente; (3) endereçar por conteúdo sobrevive a renomear o arquivo. Gravação feita com outro prompt é recusada, para o replay nunca atribuir a um prompt uma resposta que ele não produziu.
- **Em escala:** a gravação funciona como cache de produção (documento já visto = custo zero) e mapeia para S3 (prefixo = sha) ou DynamoDB.

### DEC-09 · Prompt caching, orçamento e timeout
- **Decisão:** system prompt com `cache_control`; timeout padrão de 120 s (sem streaming: respostas de ~1 k tokens); retries limitados do SDK; **orçamento de tokens por lote/invocação**.
- **Em escala:** o orçamento é um teto de dano, não de gasto planejado. Na Lambda, o controle real de custo é a concorrência reservada e `maxConcurrency` do SQS, mais alarmes.

---

## 3. Validação e decisão

### DEC-10 · `NAO_APLICAVEL` ≠ `AUSENTE` ≠ `PENDENTE`
- **Decisão:** a matriz por tipo (`rules.json`) define o que é obrigatório. Grupamento não "perde" data de pagamento; "a definir" não é inventado; dividendo com IRRF condicional **não ganha líquido calculado**.
- **Por quê:** o requisito pede tratamento de incerteza; confundir os três estados produz falso erro ou falso acerto.

### DEC-11 · Alíquota vem do aviso
- **Decisão:** líquido esperado = bruto × (1 − alíquota **do aviso**), tolerância de 0,5 unidade da última casa. Sem alíquota, a regra é `NAO_APLICAVEL`.
- **Por quê:** a alíquota é dado do documento (a de 2026 é 17,5%, mas é dado). A mutação mostrou que tolerância de 1 unidade deixava passar a troca do último dígito.

### DEC-12 · Classificação com segunda opinião
- **Decisão:** sinais ponderados por zona (campo 3 > título 2 > corpo 1), neutralizando "imputado ao dividendo obrigatório" (destino contábil do JCP). Divergência com o modelo é ERRO; título ≠ corpo vai ao humano.
- **Por quê:** classificar errado muda o tratamento tributário; uma olhada humana é barata e um JCP tratado como dividendo é caro.
- **Em escala:** a abstenção por `TITULO_DIVERGE_CORPO` cresce com o volume; é política em `rules.json`, e a auditoria amostral diz quando relaxar.

### DEC-13 · Function calling de verdade, com o código no controle
- **Decisão:** depois da extração o modelo recebe o **registro normalizado** (não o PDF) e **só as tools do tipo**. Cada pedido passa por allow-list + argumentos **idênticos** ao extraído; o resultado volta como `tool_result`; máximo de 4 turnos. O veredito é o resultado da tool; o parecer é informativo. Tool obrigatória não pedida é executada pelo orquestrador.
- **Por quê:** o enunciado exige tool calling; sem essas travas ele seria cerimonial ou perigoso (o modelo "validando" valores inventados). Conversa gravada; no replay cada pedido é reexecutado e comparado.
- **Em escala:** custo adicional ≈ 1 chamada pequena por documento (o registro, não o PDF). Se o custo importar, a conversa pode ser desligada: o orquestrador já executa as mesmas tools sozinho.
- **Detalhes:** [skill `lexis-function-calling`](../../.github/skills/lexis-function-calling/SKILL.md).

### DEC-14 · Confiança em níveis discretos, com motivos
- **Decisão:** ALTA/MÉDIA/BAIXA + lista de motivos, não uma nota numérica.
- **Por quê:** não há conjunto rotulado para calibrar probabilidade; um número seria falsa precisão.
- **Em escala:** com vereditos acumulados da auditoria amostral, cada nível pode virar uma **taxa de acerto medida** por campo e tipo. A tabela de banco já guarda campo errado e valor certo para isso.

### DEC-15 · Tabela de decisão legível, limiar a priori
- **Decisão:** sete linhas, a primeira verdadeira vence, cada uma com teste. Campo crítico ≥ MÉDIA, fixado antes de olhar os documentos.
- **Por quê:** a decisão é explicável em uma frase ("linha L2: golden não encontrado") e não foi ajustada aos 8 documentos.
- **Em escala:** o limiar é recalibrado pelos vereditos reais, não por intuição.

### DEC-16 · `para_aprovar`: o que destrava a aprovação
- **Decisão:** quando não aprova, o registro diz cada bloqueio, a linha que ele aciona, a decisão se **só ele** fosse resolvido e a decisão com **todos** resolvidos. Simulação determinística sobre a tabela, sem modelo nem reprocessamento.
- **Por quê:** o operador age sobre o que realmente bloqueia (doc 05: nenhuma das duas regras de data basta sozinha; juntas, levam a L7).

### DEC-17 · Base de referência: match exato, nome só sugere
- **Decisão:** lookup exato por ISIN/ticker/CNPJ; nome parecido gera uma *sugestão* explícita para o operador, nunca confirma nem corrige. Sem RAG nem banco vetorial. Um CNPJ pode ter uma linha por classe (ON, PN, unit): ele confirma o emissor, e a classe vem de ISIN/ticker; CNPJ sozinho com várias classes é `AMBIGUOUS`.
- **Por quê:** a base tem 12 linhas estruturadas; match exato é mais auditável.
- **Em escala:** acima de ~100 mil linhas, a base vai para tabela indexada (no mesmo banco). Hoje `Golden` é classe concreta: ao migrar, extrair uma porta `BaseReferencia`.

### DEC-18 · Dígito verificador de ISIN/CNPJ não é validado
- **Decisão:** valida-se **formato + igualdade com a base**.
- **Por quê:** 10 de 12 ISINs e 11 de 12 CNPJs da base (sintética) falhariam. Em produção, validar o dígito.

### DEC-19 · Calendário B3 embutido (2024–2030), só AVISO
- **Decisão:** feriados fixos + móveis calculados pela Páscoa, sem arquivo para manter. "ex = dia útil seguinte à data com" é AVISO. Fora de 2024–2030, só fins de semana, e o detalhe da regra diz isso.
- **Por quê:** um feriado extraordinário não previsto geraria falso erro **bloqueante**. Não foi conferido contra o calendário oficial.
- **Revisitar se:** houver integração com o calendário oficial; aí a regra pode virar ERRO.

---

## 4. Scan

### DEC-20 · Duas leituras de métodos diferentes + OCR + teto MÉDIA
- **Decisão:** leitura A (transcrição → pipeline textual) e leitura B (extração direta da imagem), com **concordância campo a campo**; OCR local (Tesseract) como terceiro leitor independente; confiança limitada a MÉDIA. OCR que discorda bloqueia (`OCR_NAO_CORROBORA`).
- **Por quê:** duas leituras do **mesmo** modelo têm erros correlacionados.

### DEC-21 · Sem OCR independente, scan sempre vai ao humano (L5)
- **Decisão:** `revisao_scan_sem_ocr_independente` (política). Com OCR corroborando, o scan segue o caminho normal (aprovável com MÉDIA).
- **Por quê:** a concordância entre leituras do mesmo modelo é evidência fraca, e olhar um scan custa menos que aprovar um valor errado.

### DEC-22 · O OCR é uma etapa gravada
- **Decisão:** `c_replay/<sha>/ocr.json`, como as respostas do modelo. O replay nunca roda o Tesseract da máquina.
- **Por quê:** o mesmo lote dá o mesmo resultado em qualquer ambiente. O OCR do doc 07 foi gravado depois, na imagem Docker, com `--modo auto` (nenhuma chamada à API): corrobora os 11 campos verificáveis, e o doc 07 passa a `APROVADO_AUTO` com MÉDIA; com `--sem-ocr`, volta para revisão.
- **Em escala:** scans são a classe mais cara e arriscada; é o estrato que a auditoria amostral deve cobrir com taxa maior.

### DEC-23 · Mutação do scan simula um OCR que concorda
- **Decisão:** como o scan sem OCR já vai sempre à revisão, qualquer defeito injetado seria "detectado" trivialmente. O controle e as mutações do scan simulam um OCR concordante para testar as **demais** barreiras. A decisão real do doc 07 é coberta pelos testes do pipeline.

---

## 5. Auditoria e dados

### DEC-24 · Trilha encadeada por hash (detecta, não impede)
- **Decisão:** cada linha de `auditoria.jsonl` e `revisoes.jsonl` carrega `hash_anterior` e `hash`. `lexis auditar` confere a cadeia, cada registro contra o selo e cada decisão humana.
- **Limite honesto:** detecta adulteração, mas quem reescreve a pasta inteira recalcula a cadeia. Impedir é papel do armazenamento imutável (Object Lock).

### DEC-25 · Identidade por conteúdo e idempotência
- **Decisão:** SHA-256 no cache e na idempotência; `REUTILIZADO` só com as mesmas versões (pipeline, regras, prompt, base, schema); falha nunca é reaproveitada; mesmo ISIN + tipo + data com em PDFs diferentes do lote gera `DUPLICATA_POSSIVEL` (ERRO): os dois vão à revisão, porque aprovar os dois lançaria o evento em dobro. Entre execuções, a duplicata é consultada no banco (`consultas.sql`), não bloqueia.
- **Em escala:** duas execuções concorrentes do mesmo documento duplicam custo (mesmo resultado). Escrita condicional no DynamoDB resolveria; não implementada.

### DEC-26 · Falha é um registro explícito
- **Decisão:** `FALHA_PROCESSAMENTO` com código; nunca derruba o lote nem vira dado parcial.

### DEC-27 · Logs só com ids, hashes, códigos e contagens
- **Decisão:** nunca texto do documento, valores ou segredos; erro inesperado traz *onde* (arquivo:linha), nunca a mensagem. Trechos de evidência ficam **no JSON de saída** (necessários para auditar sem reabrir o PDF), nunca nos logs.

### DEC-28 · Banco SQL como projeção, não como fonte da verdade
- **Decisão:** cada execução é projetada em MySQL 8.4 para consultas operacionais (fila de revisão por prazo, histórico por ISIN, duplicatas entre execuções, campos fracos). A **fonte da verdade** continua sendo os JSONs selados; o banco é reconstruível (`lexis db importar`, idempotente) e cada linha carrega o hash do JSON de origem.
- **Alternativa rejeitada:** banco como registro único. Dois registros oficiais podem divergir; um selado e uma projeção com o hash dele, não.
- **SQL portátil:** SQLAlchemy Core sem tipo/função de um banco só: MySQL no compose, SQLite nos testes, SQL Server trocando o driver. Opcional: sem `LEXIS_DB_URL` nada muda.
- **Em escala:** é exatamente o que **não escala em arquivos**. Índices nas consultas reais: `(decisao, data_pagamento)` para a fila, `isin`, `sha256`, `(emissor, tipo_evento, data_com)` para duplicatas.
- **Revisitar se:** o banco tiver trilha imutável própria (ex.: SQL Server Ledger) e a auditoria aceitar o banco como registro.

### DEC-29 · Avaliação agnóstica ao documento (sem gabarito manual)
- **Decisão:** não há "resposta esperada" por documento: ela só mediria o conjunto em que o sistema foi ajustado. Duas medidas valem para **qualquer** lote:
  1. **Mutação** (`lexis avaliar`): parte dos documentos que o sistema aprova, injeta defeitos controlados (derivados do próprio documento ou da base) e mede se deixam de ser aprovados. Mede as barreiras do código, não o modelo. **53/53 detectados** + limites conhecidos reportados à parte (injeção parafraseada; data real de outro campo); o CI falha se algum detectável passar.
  2. **Auditoria amostral dos `APROVADO_AUTO`** (no banco): o erro que importa é o **falso aprovado automático**, e a revisão humana nunca o revela. Sorteio **estratificado** (tipo × nativo/scan, mínimo 1 por estrato), às cegas, reprodutível pela semente; taxa com **intervalo de Wilson de 95%** (0 erros em 10 auditados ainda deixa o limite superior em ~28%; em 100, ~3,7%).
- **Como ler os 53/53:** as mutações foram escritas por quem conhece as regras; é teste de regressão da lógica, não estimativa de desempenho em produção. n é pequeno.

---

## 6. Console e segurança

### DEC-30 · Console local, com token por subida
- **Decisão:** só loopback; token aleatório por subida; cabeçalho `Host` conferido; no container, `serve --container` (recusado fora de um) e a porta publicada só em `127.0.0.1`. O token vai no fragmento da URL e fica em `sessionStorage`.
- **Por quê:** o servidor lê PDFs hostis e pode gastar dinheiro; qualquer página no navegador alcança `localhost`.

### DEC-31 · Login com banco; revisão registra o usuário autenticado
- **Decisão:** com `LEXIS_DB_URL`, login com scrypt + sal, sessão em cookie `HttpOnly`/`SameSite=Strict` (banco guarda só o SHA-256), bloqueio após 5 erros em 15 min. A decisão humana registra o **usuário autenticado** (o nome digitado é ignorado).
- **Conta:** criada na tela de login com e-mail (identificador) e apelido (como a pessoa aparece nas revisões); `LEXIS_DOMINIOS_EMAIL` restringe quem pode se cadastrar. O e-mail não é confirmado (o servidor não envia e-mail): o domínio limita, mas não prova, que o endereço é de quem se cadastrou.
- **Custos aceitos:** o e-mail é dado pessoal e passa a ficar na trilha (`revisoes.jsonl` e banco), como identificador do revisor. O cadastro responde 409 para e-mail já usado, então ele revela quais e-mails têm conta (o login continua sem revelar); o token por subida limita quem chega a perguntar. Não há limite de cadastros por tempo: aceitável no console local, necessário antes de expor o serviço.
- **Em escala:** SSO corporativo (OIDC/Azure AD) traz o e-mail já verificado e o desligamento automático de quem sai; como o identificador já é o e-mail, a troca não muda a trilha.
- **Limite:** login local não substitui identidade corporativa (ver SSO na [tabela de não-fazer](#7-o-que-decidi-não-fazer-e-por-quê)).

### DEC-32 · Decisão do operador nunca altera o registro
- **Decisão:** num documento em `REVISAO_HUMANA`, o operador marca cada motivo como conferido (obrigatório para aprovar; o servidor confere de novo), escolhe `APROVADO_NA_REVISAO` ou `REJEITADO_NA_REVISAO`, justifica e confirma. A decisão fica **ao lado** do registro, presa ao SHA-256 dele.
- **Fora de escopo, de propósito:** corrigir campos e revalidar (reabriria normalização, regras e decisão) e refletir a decisão no `relatorio_excecoes` (que descreve a execução automática).
- **Em escala:** a fila humana é o gargalo: com abstenção de 50%, 5 mil avisos geram 2.500 revisões. A priorização por impacto e prazo é o próximo passo.

### DEC-33 · Modelo e chave no console
- **Decisão:** o modelo aparece **só para leitura** (`LEXIS_MODEL`); a chave digitada fica **só em memória**; o modo Ao vivo exige confirmação explícita.
- **Por quê:** gravações e mutação só valem para o modelo avaliado; oferecer modelos não medidos troca qualidade medida por opinião. Chave é segredo, não dado.

### DEC-34 · Front sem biblioteca de componentes, CSP estrita
- **Decisão:** CSS próprio com *design tokens*; React escapa texto por padrão; `dangerouslySetInnerHTML` proibido por lint; `@radix-ui/react-tabs` (não injeta `<style>`) e `<dialog>` nativo em vez de `react-dialog` (que injeta estilo).
- **Por quê:** a CSP `style-src 'self'` e a identidade visual trocável em um só lugar.

### DEC-35 · Cadeia de suprimentos
- **Decisão:** lockfile com hashes (`--require-hashes`), `npm ci`, `pip-audit`, `npm audit`, `gitleaks`, `mypy --strict`, `ruff` com regras de segurança, CI em quatro jobs (qualidade, front, Docker, e2e).

### DEC-36 · Container endurecido
- **Decisão:** usuário sem root, FS somente leitura, `cap_drop: ALL`. Sem `no-new-privileges`: com o AppArmor do Ubuntu ele bloqueia o exec do Python; usuário não-root + nenhuma capability já impedem um binário setuid de ganhar privilégio.

---

## 7. O que decidi não fazer (e por quê)

| Não fiz | Motivo | Quando faria |
|---|---|---|
| Agente autônomo / multiagente, LangChain/LangGraph | Fluxo conhecido; autonomia reduz previsibilidade e auditabilidade | Tarefas abertas, sem fluxo fixo |
| RAG / banco vetorial | Base de 12 linhas estruturadas; match exato é mais auditável | Catálogo grande e textual |
| Banco como fonte única da verdade | Os JSONs selados são o registro; o banco é projeção reconstruível | Banco com trilha imutável própria aceito pela auditoria |
| Fila e workers concorrentes no console | O console processa uma execução por vez; a escala horizontal está em S3 → SQS → Lambda | Volume que o console local não comporte |
| SSO (OIDC/SAML), papéis e MFA | O login local atende a identidade do operador na trilha; num banco de investimento, identidade vem do provedor corporativo, com MFA e papéis (operador × auditor × admin) | Qualquer uso fora da máquina local |
| Implantar na AWS e escrever IaC | Sem conta/credenciais; o código está preparado e testado só com clientes falsos | Antes de qualquer uso real |
| Idempotência concorrente (DynamoDB) | No pior caso, dois workers geram o mesmo resultado (custo duplicado) | Volume com reentregas frequentes |
| Escolher o modelo no console | Só o Sonnet tem evidência; oferecer outros troca medição por opinião; o Haiku roda sem fallback do servidor | Outro modelo medido pela auditoria amostral, em modo sombra |
| Segundo provedor ou LLM gratuita | O replay já elimina o custo de avaliar; modelo não calibrado produz resultado sem evidência; planos gratuitos podem reter conteúdo e têm limite de taxa que acionaria o circuit breaker. A porta `Extrator` é o ponto de extensão | Exigência de rodar localmente ou de redundância de provedor |
| Chave de API em banco | Chave é segredo, não dado: num banco vira mais um lugar para vazar. Local: `.env`; nuvem: Secrets Manager | Nunca |
| Cascata de modelos (barato → forte), self-consistency | Otimizações de custo/calibração sem base com 8 documentos | Volume alto + vereditos da auditoria amostral |
| Calendário oficial da B3 | O embutido cobre feriados regulares e é só AVISO | Integração com o calendário oficial |
| Retificação/supersede de avisos | Exige histórico de eventos por emissor (o doc 04 anuncia um complementar) | Fluxo contínuo de avisos |
| Validar dígito de ISIN/CNPJ | Base sintética inválida | Dados reais |
| WORM, retenção e mascaramento automáticos | A cadeia **detecta** adulteração mas não a **impede**; política em [security_and_audit.md](../f_governance/security_and_audit.md) | Requisito regulatório |
| Corrigir campos e revalidar na ferramenta | Reabriria normalização, regras e decisão; a ficha diz o que corrigir e onde | Quando a auditoria precisar do valor corrigido no console e houver aprovação por quatro olhos |
| `strict` na tool de extração | A gramática excede o limite do provedor (HTTP 400) | Se o limite subir ou o contrato virar uma lista de campos |
| Streaming das respostas | Respostas curtas (~1 k tokens de saída); timeout de 120 s basta | Saídas longas ou `max_tokens` alto |
| Várias amostras por documento | O lote é **uma** execução; a variância está descrita no README | Volume e conjunto rotulado |
| Biblioteca de componentes/CSS de terceiros | CSP estrita e identidade trocável | — |
| Skills de terceiros | Sem aprovação do dono do repositório | Com aprovação |

---

## 8. Premissas

Documentadas porque o enunciado as deixa em aberto; ajustáveis em `rules.json` (`politica`).

- **"Baixa confiança"** = campo crítico `INCERTO`, `AUSENTE`, com regra ERRO reprovada ou nível BAIXA. Campo crítico precisa ser ≥ MÉDIA.
- **Coerência de datas:** `ex > com`; `pagamento ≥ com` e `≥ ex`; `crédito ≥ com`; ex = dia útil seguinte à data com (AVISO); datas a mais de 550 dias da aprovação sugerem erro de leitura de ano. Aprovação em fim de semana é só informativa (AGE/RCA podem ocorrer).
- **"Pagamento"** é só a data de pagamento **em dinheiro**; "crédito das ações" (bonificação) é outro campo. O "custo atribuído" da bonificação é base fiscal, não provento.
- **Doc 03** (título "Dividendos", corpo de JCP): prevalece o corpo, mas vai à revisão (política `revisao_por_titulo_diverge_corpo`).
- **Doc 08** (emissor fora da base): `GOLDEN_NAO_ENCONTRADO` (ERRO), sempre revisão, sem correção automática.
- **Documento de várias páginas escaneadas ou misto:** não suportado ⇒ `FALHA_PROCESSAMENTO` explícita.
- **Custo:** estimativa por preço de lista; modelo sem preço ⇒ `null`.
- **Idioma:** README, mensagens e campos de saída em PT-BR; identificadores do domínio também.

---

## 9. Em escala (milhares de documentos)

O lote entregue tem 8 documentos; **a ground truth implícita, os prompts, as regras e os limiares foram ajustados sobre eles**. Nada acima prova acurácia em produção. O que já está no código e o que falta:

| Tema | Hoje | Em milhares de documentos | Situação |
|---|---|---|---|
| **Medir o erro que importa** | Mutação (regressão da lógica) | Falso aprovado automático por **auditoria amostral estratificada**, com IC de 95% | **Feito** (`lexis auditoria`, tabela `auditoria_amostral`) |
| **Consultas operacionais** | Relatório por execução | Fila de revisão por prazo, histórico por ISIN, duplicatas entre execuções, campos fracos por tipo | **Feito** (`a_src/c_database/consultas.sql`, índices) |
| **Identidade do operador** | Login local | SSO corporativo + papéis + MFA | Login feito; SSO falta |
| **Calibrar confiança** | Níveis discretos a priori | ALTA = taxa de acerto **medida** por campo e tipo | Falta: precisa de vereditos acumulados (a tabela já guarda campo errado e valor certo) |
| **Capacidade da fila humana** | Abstenção de 50% no lote (4 de 8 não aprovados automaticamente) | 5 mil avisos ⇒ ~2.500 revisões: priorizar por impacto (valor × posição) e prazo; a calibração reduz abstenção sem aumentar o falso aprovado | Falta |
| **Rótulo sem trabalho manual** | Nenhum | Conferência com o que vem depois (conciliação, custódia, proventos publicados por B3/CVM) como mais uma fonte de veredito | Falta |
| **Troca de modelo e deriva** | Um modelo avaliado | Modo sombra com o novo modelo; deriva por emissor/layout (abstenção, divergência de classificação, discordância do OCR) | Falta: as colunas para medir já estão no banco |
| **Custo por documento** | ≈ US$ 0,21 por 8 (≈ 49 mil tokens) | Prompt caching (já ativo), Batch API, cascata de modelos apenas com evidência | Batch API e cascata: falta |
| **Processamento** | Sequencial por processo | Documentos independentes: S3 → SQS → Lambda (1 por invocação), DLQ | Handler pronto, **não implantado** |
| **Idempotência concorrente** | SHA-256 + versões | Escrita condicional (DynamoDB) | Falta |
| **Base de referência** | CSV em memória | > ~100 mil linhas: tabela indexada (porta `BaseReferencia`) | Falta |
| **Relatório agregado** | Por execução | Agregador em nuvem (Athena sobre `json/`, ou o próprio banco) | Falta |
| **Trilha imutável** | Cadeia de hashes | Object Lock (Firehose → S3) | Falta (política documentada) |
| **Egress de dados** | Lote sintético | DPA/zero-retention, região, classificação do dado | Falta (exigência de compliance) |

**Ordem sugerida:** (1) coletar vereditos da auditoria amostral, porque tudo que é calibração depende deles; (2) priorizar a fila humana; (3) SSO e papéis; (4) implantar o caminho S3 → SQS → Lambda com Object Lock; (5) só então otimizar custo.
