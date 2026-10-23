# Testes, avaliação e auditabilidade

O que foi medido, **como**, o que a execução real encontrou e o que **não** foi testado. Leia os números como medidas **desta amostra de 8 documentos** com um modelo não determinístico, não como acurácia em produção. Para o que muda com milhares de documentos: [decisions.md §9](../g_decisions/decisions.md#9-em-escala-milhares-de-documentos).

## 1. De onde vêm os números

- A extração e o function calling do lote são **respostas reais** do `claude-sonnet-5-5`, gravadas em [`c_replay/`](../../c_replay) (`"origem": "API"`) por `lexis run --modo live`.
- O replay padrão reproduz esse resultado sem rede nem chave e é o que gerou o lote entregue em `f_data/b_output/report_261023_2135/` (`extrator: replay`; tokens e custo zerados nos JSONs).
- A execução live que produziu as gravações teve **8/8 documentos com todas as tools de validação pedidas pelo modelo**, ≈ 49 mil tokens, **≈ US$ 0,21** (estimativa por preço de lista; esses números **não** estão nos JSONs atuais: `lexis run --modo live --forcar` os regrava).
- Depois dela, a política de scan mudou e o OCR local do doc 07 foi gravado à parte (`--modo auto`, sem chamada à API): a decisão foi recalculada sobre as mesmas gravações.
- **Não há gabarito manual**, de propósito: uma resposta esperada para cada um destes 8 documentos mediria só o conjunto em que o sistema foi ajustado. Os testes de pipeline sobre o lote verificam **comportamentos** (motivo e ficha certos para cada armadilha, scan com teto MÉDIA, `para_aprovar`), não uma planilha de respostas.

## 2. Resultado sobre o lote

| # | Documento | Tipo | Decisão | Por quê |
|---|---|---|---|---|
| 01 | Energética Vale do Tietê | Dividendo | `APROVADO_AUTO` | IRRF de 10% é condicional (> R$ 50 mil/mês): **não** há líquido por ação, e o código não calcula nenhum |
| 02 | Banco Meridional | JCP | `APROVADO_AUTO` | Líquido confere com bruto × (1 − 17,5%) |
| 03 | Siderúrgica Paranaense | JCP | `REVISAO_HUMANA` | Título diz "Dividendos"; o corpo (TJLP, "remuneração do capital próprio", IRRF) é JCP. Prevalece o corpo, mas o conflito vai ao humano porque muda o tratamento tributário |
| 04 | Rede Varejo | JCP | `AGUARDA_EMISSOR` | Pagamento "a definir": o campo fica `PENDENTE` (nunca inventado); a ação é aguardar o aviso complementar |
| 05 | Aurora Saneamento | Dividendo | `REVISAO_HUMANA` | Pagamento (10/07) anterior à data com (15/07). Nenhuma das duas regras de data basta sozinha para aprovar; juntas, levam a L7 |
| 06 | Petroquímica Litoral | Grupamento 10:1 | `APROVADO_AUTO` | Sem valor, moeda nem pagamento: `NAO_APLICAVEL`, não "ausente" |
| 07 | Telecom Norte (scan) | JCP | `APROVADO_AUTO` | As duas leituras do modelo de visão concordam, os valores batem com a base **e o OCR local (Tesseract), leitor independente do modelo, corrobora** os 11 campos verificáveis por texto. Confiança **limitada a MÉDIA**. Sem a gravação de OCR (`--sem-ocr`), iria ao humano (`OCR_INDISPONIVEL`, L5) |
| 08 | Construtora Horizonte | Bonificação 1:20 | `REVISAO_HUMANA` | Emissor/ISIN/ticker/CNPJ **fora da base de referência**. O "custo atribuído" é base fiscal, não provento |

Contagem: 4 `APROVADO_AUTO`, 1 `AGUARDA_EMISSOR`, 3 `REVISAO_HUMANA`. **Abstenção: 50%.**

## 3. Testes

| Suíte | O que cobre | Tamanho |
|---|---|---|
| `b_tests/a_unit` | Normalização, coerência, classificação, base de referência, evidência, decisão, tools, **function calling** (loop, correção pelo modelo, truncamento, recusa, limite de turnos, gravação/replay, fallback, erros do provedor), extração/gravações, ingestão com PDFs sintéticos, calendário B3, cadeia de hashes, **arquitetura** (núcleo sem I/O, sem adaptadores, sem camada acima) | 328 testes Python no total |
| `b_tests/b_integration` | Pipeline fim a fim, lote, **AWS com cliente S3 falso**, **API do console** (autenticação, Host, CSP, upload, ciclo de execução, decisão do operador), resiliência e custos, **contratos** do schema e da API, avaliação, **banco SQL** (projeção idempotente, auditoria amostral, consultas documentadas, usuários e sessões), **login pela API**, integridade da trilha | |
| `b_tests/c_security` | Injeção (modelo resistente e obediente), lote real sem alerta de segurança | |
| Front (`a_src/a_frontend`) | **92** testes (Vitest + Testing Library, com `axe-core` em cada tela e aba) e **7** de ponta a ponta (Playwright em Chromium contra o servidor real, em replay, com axe incluindo contraste e checagem de violações de CSP) | |

Qualidade estática: `ruff` (inclui regras `S` de segurança), `mypy --strict`, `pip-audit`, `tsc --strict`, ESLint (`typescript-eslint` strict + `jsx-a11y`), Prettier e `npm audit` limpos. O CI roda tudo (Python, front, Docker, e2e) mais `gitleaks`.

Acessibilidade testada: axe em cada tela e aba, axe com contraste no e2e e um e2e que usa o console inteiro só pelo teclado, com foco sempre visível. **Não** testado: leitor de tela de verdade.

## 4. Avaliação por mutação (`lexis avaliar`)

Parte dos documentos que o próprio sistema aprova, injeta defeitos controlados (o resultado esperado é conhecido por construção) e mede se deixam de ser aprovados. Trabalha em memória sobre as extrações gravadas: sem rede nem chave.

| Classe | Detectados |
|---|---|
| Documento realmente errado | 24/24 |
| Modelo errou | 19/19 |
| Injeção | 7/7 |
| Scan | 3/3 |
| **Global** | **53/53** |

Mais **1 limite conhecido** que passa (`injecao_parafraseada_altera_bruto_modelo_obediente`): valor plausível injetado e citado no próprio documento, sem segunda fonte para contradizê-lo.

**Agnóstica ao lote:** cada defeito sai do próprio documento (o último dígito do valor que ele cita, uma data derivada da dele, a proporção invertida) ou da base de referência (ISIN, ticker e CNPJ de **outro** emissor cadastrado); nenhum caso é escrito para um arquivo. Um teste roda a avaliação sobre os mesmos PDFs renomeados e em outra ordem e exige o mesmo resultado.

**O que ela encontrou:** na primeira rodada, 2 falsos auto-aprovados reais (tolerância do líquido larga demais; discordância do OCR tratada só como aviso). Corrigidos.

**Revisão de 2026-10-23:** uma revisão crítica testou defeitos que a suíte não gerava e achou 2 classes de falso auto-aprovado:

- **Citação truncada** (`R$ 0,4275000000` citado como `R$ 0,427`): o trecho existia como substring e o valor mudava. A evidência passou a recusar trecho que começa ou termina no meio de um número; a mutação ganhou `valor_bruto_truncado` e `valor_liquido_truncado` (detectados).
- **Data real de outro campo** (a data de aprovação citada como data com; a data ex citada como pagamento): **limite conhecido**, reportado como `detectavel: false` (5 casos nos docs 01, 02 e 06). Fechar exige o modelo citar o rótulo junto do valor e o código conferir a proximidade, o que muda o prompt e pede nova gravação.

Mais **6 limites conhecidos** aprovados no total (o de injeção parafraseada e os 5 acima), listados em `avaliacao_mutacao.json`.

**Scan na mutação:** como o scan sem OCR já vai sempre à revisão, qualquer defeito seria "detectado" trivialmente. Por isso o controle e as mutações do scan simulam um OCR que concorda com a transcrição, e as 3 mutações testam as demais barreiras (concordância das leituras, evidência, OCR que discorda). A decisão real do doc 07, com o OCR gravado de verdade, é coberta pelos testes do pipeline.

**Como ler os 53/53:** as mutações foram escritas por quem conhece as regras; é um **teste de regressão da lógica**, não uma estimativa de desempenho em produção. n é pequeno. As mutações partem das extrações reais, mas os defeitos são injetados em memória (**não medem o modelo**).

## 5. O que a execução real encontrou

Nenhum destes casos aparecia nas gravações simuladas anteriores; todos corrigidos, com teste de regressão:

- O modelo juntou células de tabela numa citação ("ação preferencial (PN)"). O controle de evidência pegou (`EVIDENCIA_NAO_ENCONTRADA` → revisão); o prompt passou a exigir trecho **contíguo**.
- `moeda` estava listada sem instrução, e o modelo, corretamente, respondeu `AUSENTE`. Os campos sem orientação ganharam instrução.
- Com `strict`, o modelo omitiu `percentual_declarado` porque o registro vinha em ordem diferente da do schema (ver [DEC-07](../g_decisions/decisions.md)).
- O normalizador não aceitava "1 (uma) ação nova para cada 20 (vinte)" (redação padrão), e a concordância das duas leituras do scan reprovava a mesma frase com e sem ponto final.
- A orientação "não junte linhas" fez o modelo cortar a observação tributária do doc 01 antes de "R$ 50.000,00 mensais"; a regra foi reescrita (contíguo pode atravessar quebra de linha do mesmo parágrafo).

**Variância entre execuções:** nas 4 execuções completas do lote, os docs 01 a 06 e 08 tiveram sempre a mesma decisão. O doc 07 foi para revisão uma vez, pelo defeito de concordância acima. Nos 2 testes de fumaça anteriores, o doc 02 foi para revisão (citação não contígua; `moeda` sem instrução). Toda diferença foi uma **revisão desnecessária, nunca uma aprovação indevida**. O lote entregue é a execução final, feita depois das correções.

## 6. Revisões independentes

- Na verificação de 2026-10-23 (refatoração para arquitetura hexagonal), um teste do banco que falhava de forma intermitente revelou uma **condição de corrida real**: a projeção do fim do lote e a da revisão do operador corriam juntas, e a revisão podia ficar fora do banco (`IntegrityError`). Corrigido serializando as projeções; o teste passou 15 de 15 vezes depois.

- O subagente `security-review` achou **2 furos reais** na detecção de texto oculto (CMYK e `3 Tr`).
- O `code-review` achou **8 problemas** nas portas/AWS (orçamento acumulando entre invocações, falha transitória gravada como final, circuito sobrescrevendo resultados bons, entre outros).
- Todos corrigidos com teste de regressão (`b_tests/b_integration/test_code_review.py`).

## 7. Auditabilidade (e seus limites)

Cada JSON carrega as versões que o produziram (código, regras+hash, prompt, modelo, base), a evidência de cada valor, **timestamps de início e fim, tokens, tentativas de reparo e custo estimado** (tabela de preços públicos, marcada como estimativa; modelo sem preço ⇒ `null`, nunca inventado). `auditoria.jsonl` registra execução, documento, regras com falha, tools, abertura de circuito, o SHA-256 de cada registro gravado (`registros_publicados`) e as decisões do operador.

**Trilha encadeada e `lexis auditar`.** Cada linha de `auditoria.jsonl` e de `revisoes.jsonl` carrega `hash_anterior` e `hash` (SHA-256 canônico do evento + hash da linha anterior; [`hash_chain.py`](../../a_src/b_backend/lexis/a_domain/hash_chain.py)). `lexis auditar <pasta>` confere três coisas e devolve 0/1: a cadeia (linha alterada, removida, inserida ou fora de ordem), cada `json/<documento>.json` contra o hash selado, e cada decisão do operador contra o registro sobre o qual foi tomada e contra o seu evento na trilha. O CI audita o lote entregue. A verificação usa a porta de armazenamento, então vale igual para pasta local ou S3.

**Limites:**

- O modelo **não é determinístico**: as gravações fixam **uma** amostra; regravar pode mudar o resultado.
- A cadeia **detecta** adulteração mas não a **impede**: quem reescreve tudo pode recalcular os hashes. Impedir é papel do armazenamento imutável (Object Lock na AWS).
- Os relatórios (`relatorio_excecoes.*`) são derivados dos registros e **não são selados**.
- A justificativa é montada a partir de **códigos de motivo**, não do raciocínio do modelo (o raciocínio não é devolvido pela API; o parecer do function calling é texto do modelo, informativo).

## 8. O que **não** foi testado

- Concorrência real e carga (o processamento é sequencial por processo; escala por documento independente).
- A AWS de verdade (só clientes falsos; sem IaC).
- Leitor de tela de verdade (a navegação por teclado é coberta pelo e2e).
- Acurácia em volume: n = 8. A forma de medir (auditoria amostral com IC de 95%) está implementada e documentada, mas **não há vereditos reais acumulados**.
