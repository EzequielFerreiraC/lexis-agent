import type { Catalogo, ParaAprovar as Dados } from '../api/types';
import { ROTULO_DECISAO, rotuloDoCampo } from '../lib/labels';
import { SeloDecisao } from './Badges';

/**
 * O que falta para a aprovação automática: cada bloqueio sozinho e todos juntos. É uma simulação sobre a tabela de
 * decisão feita pelo servidor (não reprocessa o documento); a tela só mostra o que veio no registro.
 */
export function ParaAprovar({ dados, catalogo }: { dados: Dados; catalogo: Catalogo | undefined }) {
  if (dados.passos.length === 0) return null;
  const bastaSozinho = dados.passos.some((p) => p.decisao_se_so_este_resolver === 'APROVADO_AUTO');
  return (
    <div className="para-aprovar">
      <h3>O que falta para aprovar</h3>
      <ul className="lista-simples para-aprovar__passos">
        {dados.passos.map((p, i) => (
          <li key={`${p.codigo}-${p.campo ?? ''}-${String(i)}`}>
            <code className="codigo-chip">{p.codigo}</code>
            {p.campo ? ` (${rotuloDoCampo(catalogo, p.campo)})` : ''}: {p.condicao}.{' '}
            {p.decisao_se_so_este_resolver === 'APROVADO_AUTO' ? (
              <strong>Basta este.</strong>
            ) : (
              <span className="suave">
                Sozinho não basta: continua em {ROTULO_DECISAO[p.decisao_se_so_este_resolver]} (linha{' '}
                {p.linha_se_so_este_resolver}).
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="nota para-aprovar__total">
        {bastaSozinho ? 'Com tudo resolvido' : 'Só com tudo resolvido junto'}:{' '}
        <SeloDecisao decisao={dados.decisao_com_todos_resolvidos} /> (linha {dados.linha_com_todos_resolvidos}
        ). Simulação sobre a tabela de decisão: não reprocessa o documento.
      </p>
    </div>
  );
}
