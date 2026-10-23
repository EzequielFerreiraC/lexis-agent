# Documentação do Lexis

Mapa dos documentos. O [README da raiz](../README.md) é a porta de entrada; aqui está o detalhe.

| Pasta | Documento | Para quem | O que responde |
|---|---|---|---|
| `a_statement/` | [statement.md](a_statement/statement.md) | todos | O que o case pediu |
| `b_plan/` | [plan.md](b_plan/plan.md) | quem quer o raciocínio original | A análise e o plano **anteriores** ao código (histórico) |
| `c_architecture/` | [architecture.md](c_architecture/architecture.md) | quem vai mexer no código | Camadas, portas e adaptadores, onde moram os dados, **diagrama da arquitetura** |
| `c_architecture/` | [pipeline.md](c_architecture/pipeline.md) | todos | O caminho de um documento, etapa por etapa, **diagrama do pipeline detalhado** |
| `c_architecture/` | [aws.md](c_architecture/aws.md) | quem vai implantar | O mapeamento para AWS (preparado, não implantado) |
| `d_skills/` | [skills.md](d_skills/skills.md) | quem audita o processo | Skills, bibliotecas, ferramentas e serviços externos, e o que cada um achou |
| `e_contracts/` | [output_record.schema.json](e_contracts/output_record.schema.json), [api.openapi.json](e_contracts/api.openapi.json) | quem integra | Contratos publicados (gerados por `lexis contratos`) |
| `f_governance/` | [defenses.md](f_governance/defenses.md) | segurança, auditoria | **Catálogo de todas as defesas**: ameaça, mecanismo, código, teste e limites |
| `f_governance/` | [security_and_audit.md](f_governance/security_and_audit.md) | segurança, compliance | OWASP LLM Top 10, NIST AI RMF, retenção, acesso, garantias de rastreabilidade |
| `g_decisions/` | [decisions.md](g_decisions/decisions.md) | todos | **Todas as decisões**, o que decidi não fazer, premissas e o que muda em escala |
| `h_operations/` | [operations.md](h_operations/operations.md) | quem opera | Como rodar: CLI, modos, variáveis, console, Docker, banco, auditoria amostral, como estender |
| `i_evaluation/` | [evaluation.md](i_evaluation/evaluation.md) | todos | Resultado do lote, testes, mutação, o que a execução real encontrou, auditabilidade e o que **não** foi testado |

**Por onde começar:** [pipeline.md](c_architecture/pipeline.md) (entender) → [decisions.md](g_decisions/decisions.md) (por quê) → [defenses.md](f_governance/defenses.md) (como está protegido) → [evaluation.md](i_evaluation/evaluation.md) (o que foi medido).

Os documentos `e_contracts/*.json` e `a_src/c_database/schema_mysql.sql` são **gerados**: não edite à mão (`lexis contratos`).
