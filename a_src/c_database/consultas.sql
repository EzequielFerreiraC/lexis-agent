-- Consultas operacionais sobre a projeção (MySQL 8.4; SQL padrão, também roda no SQLite dos testes).
-- Cada bloco começa com "-- name: <nome>"; b_tests/b_integration/test_sql.py executa todos contra o lote entregue (via lexis.h_interfaces.contracts).
-- Parâmetros nomeados (:isin) são passados pelo driver, nunca concatenados.

-- name: fila_de_revisao_por_prazo
-- O que o operador precisa resolver primeiro: revisão humana e aguardando emissor, pelo pagamento mais próximo.
SELECT d.execucao_id, d.arquivo, d.decisao, d.emissor, d.tipo_evento, d.data_pagamento, d.valor_bruto,
       m.codigo AS primeiro_motivo
FROM documento d
LEFT JOIN motivo m ON m.documento_id = d.id AND m.ordem = 0
LEFT JOIN revisao r ON r.documento_id = d.id
WHERE d.decisao IN ('REVISAO_HUMANA', 'AGUARDA_EMISSOR') AND r.id IS NULL
ORDER BY CASE WHEN d.data_pagamento IS NULL THEN 1 ELSE 0 END, d.data_pagamento, d.id;

-- name: historico_por_isin
-- Tudo o que já foi processado de um papel, em todas as execuções.
SELECT e.id AS execucao, e.modelo, d.arquivo, d.tipo_evento, d.data_com, d.data_pagamento, d.valor_bruto, d.decisao
FROM documento d
JOIN execucao e ON e.id = d.execucao_id
WHERE d.isin = :isin
ORDER BY d.data_com DESC, e.importada_em DESC;

-- name: possiveis_duplicatas_entre_execucoes
-- Mesmo emissor, tipo e data com em PDFs diferentes: aviso reenviado, retificação ou erro de leitura.
SELECT d.emissor, d.tipo_evento, d.data_com, COUNT(DISTINCT d.sha256) AS pdfs_distintos
FROM documento d
WHERE d.emissor IS NOT NULL AND d.data_com IS NOT NULL
GROUP BY d.emissor, d.tipo_evento, d.data_com
HAVING COUNT(DISTINCT d.sha256) > 1;

-- name: campos_fracos_por_tipo
-- Onde a extração mais deixa de dar confiança suficiente: guia de calibração e de melhoria do prompt.
SELECT d.tipo_evento, c.nome AS campo, c.estado, c.confianca, COUNT(*) AS ocorrencias
FROM campo c
JOIN documento d ON d.id = c.documento_id
WHERE c.estado = 'INCERTO' OR (c.estado = 'EXTRAIDO' AND c.confianca = 'BAIXA')
GROUP BY d.tipo_evento, c.nome, c.estado, c.confianca
ORDER BY ocorrencias DESC;

-- name: regras_que_mais_bloqueiam
SELECT rr.regra_id, rr.severidade, COUNT(*) AS falhas
FROM regra_resultado rr
WHERE rr.resultado = 'FALHA' AND rr.severidade <> 'INFO'
GROUP BY rr.regra_id, rr.severidade
ORDER BY falhas DESC;

-- name: falso_auto_aprovado_por_estrato
-- A métrica principal: dos aprovados automaticamente e auditados às cegas, quantos estavam errados.
SELECT a.estrato,
       COUNT(*) AS sorteados,
       SUM(CASE WHEN a.veredito IS NOT NULL THEN 1 ELSE 0 END) AS auditados,
       SUM(CASE WHEN a.veredito = 'ERRADO' THEN 1 ELSE 0 END) AS errados
FROM auditoria_amostral a
GROUP BY a.estrato
ORDER BY a.estrato;

-- name: decisoes_humanas_por_motivo
-- Revisões que o operador aprovou sem correção indicam bloqueio que poderia ser automático (calibração).
SELECT m.codigo AS motivo, r.decisao, COUNT(*) AS revisoes
FROM revisao r
JOIN motivo m ON m.documento_id = r.documento_id
GROUP BY m.codigo, r.decisao
ORDER BY revisoes DESC;
