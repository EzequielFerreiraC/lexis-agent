---
name: lexis-extend-rules
description: 'Use when adding a new corporate event type (ex.: subscrição, desdobramento), a new validation/coherence rule, a new routing policy, or a new decision-table line in the lexis project. Guides the exact files, tests and mutation to touch so routing, schema and report stay consistent.'
argument-hint: 'tipo de evento ou regra a adicionar'
---

# Estender o Lexis (novo tipo de evento, regra ou política)

Fluxo que a sessão técnica pode pedir ao vivo. Siga na ordem; cada passo tem um teste que o prende.

## Quando usar
- Novo tipo de evento (ex.: SUBSCRICAO).
- Nova regra de coerência, nova validação via tool, ou mudança de política de roteamento.

## Novo tipo de evento
1. `a_src/b_backend/lexis/a_domain/models.py`: adicione o valor em `TipoEvento` (e no enum do `esquema_extracao` em `c_extraction/prompts.py`).
2. `a_src/b_backend/lexis/a_domain/rules.json`: bloco em `tipos_evento` com `aplicabilidade` (**todos os campos de `campos`**, exceto os de `identidade`), `criticos` e `tratamento_tributario`. O teste de contrato recusa matriz incompleta.
3. `a_src/b_backend/lexis/d_validation/classification.py`: sinais em `_SINAIS` (pesos 3/2/1). Cuidado com termos que descrevem o destino contábil de outro tipo.
4. Se houver proporção ou valores novos: ajuste `a_domain/normalization.py` e a regra correspondente (próximo bloco).
5. Teste: `b_tests/a_unit/test_classification.py` (sinais) e, se tiver PDF de exemplo, um teste de comportamento em `b_tests/b_integration/test_pipeline.py` (motivo, ficha e decisão esperados para a armadilha, conferidos na leitura do PDF, não na saída do pipeline).

## Nova regra de coerência
1. Declare `id`, `severidade` (ERRO bloqueia; AVISO só vira revisão se estiver em `politica`; INFO só informa) e `descricao` em `rules.json` → `regras`.
2. Implemente em `d_validation/coherence.py` como função pura (valores já normalizados → `RegraResultado`). Use a alíquota/valores **do aviso**, nunca constantes.
3. Ligue-a a uma tool em `d_validation/tools.py` (`tools_aplicaveis`, `args_esperados`, `executar_tool`) para que o orquestrador a execute.
4. Mapeie a ação do operador em `e_decision/checklists.py` (`ACAO_POR_REGRA`).
5. Testes: `b_tests/a_unit/test_coherence.py` (caso que passa e caso que falha, incluindo borda) e **uma mutação** em `_gerar_casos` de `i_assessment/evaluation.py` que viole a regra. `lexis avaliar` precisa continuar sem falso auto-aprovado.

## Nova política ou linha da tabela de decisão
- Política (limiar, teto do scan, doc 03 auto/revisão): só `rules.json` → `politica`.
- Nova linha: `e_decision/decision_table.py` (`TABELA`, a primeira verdadeira vence; `L7` é sempre a última). Um teste por linha em `b_tests/a_unit/test_decision.py`.

## Antes de terminar
```bash
ruff check a_src/b_backend b_tests && mypy && pytest -q
lexis avaliar
```
Se o schema de saída mudou: `lexis contratos` e suba `SCHEMA_VERSION`.
Atualize a tabela "o que decidi não fazer" do README se o escopo mudou.
