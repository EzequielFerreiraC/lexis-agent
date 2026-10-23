# Relatório de exceções — execução `4a942afc426b`

Gerado em 2026-10-24 00:35 UTC · catálogo de regras v1.0+7709e71789cb · extrator: `replay`

**8 documentos:** APROVADO_AUTO 4 · AGUARDA_EMISSOR 1 · REVISAO_HUMANA 3

## Documentos que exigem atuação

| Documento | Estado | Motivos | O que conferir / fazer | Para aprovar |
|---|---|---|---|---|
| 03_siderurgica_paranaense_proventos.pdf | REVISAO_HUMANA | `TITULO_DIVERGE_CORPO` (tipo_evento) | CONFERIR_CLASSIFICACAO · esperado tipo pelo corpo/natureza: JCP · observado tipo pelo título: DIVIDENDO | basta resolver `TITULO_DIVERGE_CORPO` |
| 04_rede_varejo_jcp_sem_data.pdf | AGUARDA_EMISSOR | `CAMPO_PENDENTE_NO_AVISO` (data_pagamento) | AGUARDAR_AVISO_COMPLEMENTAR · observado A definir (vide aviso complementar) | basta resolver `CAMPO_PENDENTE_NO_AVISO` |
| 05_aurora_saneamento_dividendo_datas.pdf | REVISAO_HUMANA | `DATAS_PAGAMENTO_ANTES_DA_COM` (data_pagamento); `DATAS_PAGAMENTO_ANTES_DA_EX` (data_pagamento) | RESOLVER_INCONSISTENCIA · esperado data_pagamento >= data_com · observado data_pagamento=2026-07-10, data_com=2026-07-15 | resolver juntos `DATAS_PAGAMENTO_ANTES_DA_COM` + `DATAS_PAGAMENTO_ANTES_DA_EX` |
| 08_construtora_horizonte_bonificacao.pdf | REVISAO_HUMANA | `GOLDEN_NAO_ENCONTRADO` (emissor) | CADASTRAR_EMISSOR · observado não constam na base de referência: isin BRCNHZACNOR5, ticker CNHZ3, cnpj 09.888.999/0001-21 | basta resolver `GOLDEN_NAO_ENCONTRADO` |

## Aprovados automaticamente, com ressalvas que não bloqueiam

- 07_telecom_norte_jcp_SCAN.pdf: scan lido por modelo de visão (confiança limitada a MEDIA)

Detalhe campo a campo, evidência e justificativas: `json/<documento>.json` (seção `fichas_conferencia`).
