# Gravações das chamadas ao modelo (respostas reais)

Cada pasta é o SHA-256 do PDF (`<sha256>/<etapa>.json`). O endereço pelo conteúdo permite achar a gravação mesmo se o
arquivo for renomeado e mapeia direto para S3/DynamoDB. Todas têm `"origem": "API"`: são **respostas reais** do modelo,
gravadas por `lexis run --modo live --forcar` (procedimento: skill
[`lexis-live-recording`](../.github/skills/lexis-live-recording/SKILL.md)).

| Etapa | O que guarda |
|---|---|
| `extracao` | leitura do PDF nativo: trechos literais citados pelo modelo (tool `registrar_extracao`) |
| `transcricao`, `extracao_transcricao`, `extracao_direta` | as duas leituras independentes do scan (doc 07) |
| `validacao_tools` | a conversa de function calling: que tools o modelo pediu, com quais argumentos, o `tool_result` que recebeu e o parecer final. Vale só enquanto `pedido_sha` (registro + schemas das tools + prompts) for o mesmo |
| `ocr` | texto do OCR local (Tesseract) de um scan, quando estava disponível em `--modo auto`/`live`. O replay nunca roda o OCR da máquina: sem esta gravação, o scan fica com `OCR_INDISPONIVEL`. O doc 07 tem esta gravação (feita com `--modo auto` na imagem Docker, sem chamada à API); com `--sem-ocr` ela é ignorada |

Em `--modo replay` (padrão) nada é chamado: as leituras são reaproveitadas e, em `validacao_tools`, cada pedido do modelo
passa de novo pela allow-list, pela conferência de argumentos e pela execução real da tool; o resultado é comparado com
o gravado. O veredito nunca sai da gravação.

| Documento | SHA-256 | Etapas | Modelo | Origem |
|---|---|---|---|---|
| 01_energetica_vale_tiete_dividendo.pdf | `e49afdf81d2a1e4a74985e78fa0ea3639633cfa19f5dba633a2b545d115153cb` | extracao · validacao_tools | claude-sonnet-5-5 | API |
| 02_banco_meridional_jcp.pdf | `64e0787afd32c0d99e5407a5fbc6f5048245ba70826563d0b14205074b970668` | extracao · validacao_tools | claude-sonnet-5-5 | API |
| 03_siderurgica_paranaense_proventos.pdf | `a21a294ac3ededbb6fdef195be0edb0572069544e0b73f6fc1918fa77d6b0e85` | extracao · validacao_tools | claude-sonnet-5-5 | API |
| 04_rede_varejo_jcp_sem_data.pdf | `37f846a73cb5486b543bb1e580144c8d94eafee4aa7396424637c063a3bfbb83` | extracao · validacao_tools | claude-sonnet-5-5 | API |
| 05_aurora_saneamento_dividendo_datas.pdf | `925b6eb09fbcaecf81d3c1d125e041edd1460fed23d6a67bf10f8a6b170e9567` | extracao · validacao_tools | claude-sonnet-5-5 | API |
| 06_petroquimica_litoral_grupamento.pdf | `147d83f038f6ca94495a5d5248f36a6feedee7ae9a5cebc011d40e1f14d68068` | extracao · validacao_tools | claude-sonnet-5-5 | API |
| 07_telecom_norte_jcp_SCAN.pdf | `cf4af08dd23f507ae72b852d86827bbee6c3fe2d0e31f96e70bc74ea4238c45f` | extracao_direta · extracao_transcricao · transcricao · validacao_tools · ocr | claude-sonnet-5-5 (`ocr`: Tesseract local) | API (`ocr`: OCR_LOCAL) |
| 08_construtora_horizonte_bonificacao.pdf | `a509637f4b258454309e1d21e81beca56701a78624b8a6a6f9a6b0ec9389b0e5` | extracao · validacao_tools | claude-sonnet-5-5 | API |
