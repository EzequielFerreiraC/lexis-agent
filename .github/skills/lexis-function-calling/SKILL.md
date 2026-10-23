---
name: lexis-function-calling
description: 'Use when changing, adding or debugging the validation tools the model calls (function calling) in the lexis project: tool schemas, the tool loop, the tool_result contract, the recording/replay of the tool conversation, or the prompt that drives it. Lists the invariants that keep the model from deciding anything and the tests that pin each one.'
argument-hint: 'tool ou comportamento do loop a alterar'
---

# Function calling de validação (lexis)

O modelo **pede** as tools; o **código** executa e decide. Esta skill existe para que uma mudança no loop não
transforme o modelo em quem valida.

## Onde vive cada parte
| Parte | Arquivo |
|---|---|
| Porta (`PedidoTools`, `ConversaTools`, `ChamadorDeTools`, `Atender`) | `a_domain/ports.py` |
| Prompt do loop (`PROMPT_TOOLS`, entra no `prompt_sha`) | `c_extraction/prompts.py` |
| Requisição à API (orçamento, `effort`, fallback, `refusal`, erros codificados) | `g_adapters/anthropic_api.py` → `ExtratorAnthropic.chamar` |
| Gravação e replay da conversa (`<sha>/validacao_tools.json`) | `c_extraction/recordings.py` → `ChamadorComCache` |
| Schemas das tools, `atender`, orquestrador (sem rede) | `d_validation/tools.py` |
| Loop com o modelo (`ChamadorAnthropic`, `MAX_TURNOS`) e fábrica `chamador_anthropic` | `g_adapters/anthropic_api.py` |
| Ligação no núcleo (`Contexto.cliente_factory`, `Contexto.chamador_factory`) | `f_application/pipeline.py`; montada em `g_adapters/local_execution.py`, `h_interfaces/api/service.py` e `h_interfaces/aws_lambda.py` |
| Resumo no JSON de saída (`auditoria.validacao_pelo_modelo`) | `f_application/analysis.py` |

## Invariantes (não quebre; cada um tem teste)
1. **Allow-list fechada e só as aplicáveis.** O modelo recebe apenas `tools_aplicaveis(tipo)`; qualquer outro nome
   volta como erro `FORA_DA_ALLOW_LIST`/`NAO_APLICAVEL_AO_TIPO`. Tools são somente leitura.
2. **Argumentos iguais ao extraído.** `atender` compara com `args_esperados`; divergência volta ao modelo como
   `tool_result` com `is_error` e `campos_divergentes` (o NOME do campo, nunca o valor certo).
3. **Veredito = resultado da tool.** O parecer do modelo é informativo (`parecer_do_modelo`) e não entra em `regras`.
4. **Rede de segurança.** Toda tool obrigatória que o modelo não pediu (ou pediu errado até o fim) é executada pelo
   orquestrador com origem `ORQUESTRADOR`.
5. **Contrato da API.** Tools de validação com `strict: true`, dentro dos limites que o provedor aplica por
   requisição (≤ 16 parâmetros anuláveis/união, ≤ 24 opcionais, gramática compilada pequena; acima: HTTP 400):
   por isso os campos são `string` opcionais (ausente = omitido, sem `null`). A tool de extração **não** usa
   strict (gramática grande demais) e fica protegida pelo pydantic + 1 reparo; `tool_choice` automático
   (forçar é rejeitado pelos modelos atuais); todos os `tool_result` de um turno numa única mensagem `user`; o
   conteúdo do assistente volta **intacto** (inclui blocos de raciocínio); nunca execute tools de uma resposta com
   `stop_reason` `max_tokens` ou `refusal`; limite de `MAX_TURNOS`.
6. **Falha não derruba a validação.** Erro do provedor, recusa ou orçamento viram `encerramento="ERRO:<código>"`,
   com os tokens gastos contabilizados; conversa com erro **não é gravada**.
7. **Replay honesto.** A gravação guarda quem pediu qual tool com quais argumentos. No replay, cada pedido passa de
   novo por `atender` (execução real) e o resultado é comparado com o gravado (`avisos` se mudou). A gravação vale
   só se `pedido_sha` (registro + schemas das tools + `prompt_sha`) for igual; senão `GRAVACAO_DESATUALIZADA`.

## Mudou algo? Faça nesta ordem
1. Schema de tool novo/alterado: `_tool(...)` em `tools.py` (sempre via `_tool`, que aplica `strict` e
   `required`). Ajuste `args_esperados`, `executar_tool` e `tools_aplicaveis`.
2. Prompt alterado: `PROMPT_TOOLS`. Isso muda `prompt_sha` e invalida **todas** as gravações de tools.
3. Testes: `b_tests/a_unit/test_function_calling.py` (loop, correção, truncamento, recusa, limite, replay) e
   `b_tests/a_unit/test_tools.py` (allow-list, argumentos, veredito).
4. Regrave com o modelo real (skill `lexis-live-recording`) e confira no JSON:
   `auditoria.chamadas_de_tools[*].origem == "MODELO"` e `auditoria.validacao_pelo_modelo.encerramento == "end_turn"`.

```bash
ruff check a_src/b_backend b_tests && mypy && pytest -q b_tests/a_unit/test_function_calling.py b_tests/a_unit/test_tools.py
```
