import { Link } from 'react-router-dom';
import type { ExecucaoItem } from '../api/types';
import { formatarDataHora } from '../lib/format';
import { ROTULO_DECISAO, ROTULO_MODO, TOM_DECISAO, rotuloDe } from '../lib/labels';
import { SeloEstadoJob } from './Badges';
import { Icone } from './Icon';

/** Uma linha por execução: quando, modo, quantos documentos e como terminaram. Usada em "recentes" e no histórico. */
export function ListaExecucoes({ itens }: { itens: ExecucaoItem[] }) {
  return (
    <ul className="lista-linhas">
      {itens.map((e) => (
        <li key={e.id} className="lista-linhas__item">
          <Link className="lista-linhas__link" to={`/execucoes/${e.id}`}>
            {formatarDataHora(e.criada_em)} · {rotuloDe(ROTULO_MODO, e.modo)} · {e.total} documento(s)
          </Link>
          <span className="lista-linhas__lado">
            <span className="chips">
              {Object.entries(e.contagem).map(([decisao, n]) => (
                <span
                  key={decisao}
                  className={`chip chip--${(TOM_DECISAO as Record<string, string | undefined>)[decisao] ?? 'neutro'}`}
                >
                  {String(n)} {rotuloDe(ROTULO_DECISAO, decisao).toLowerCase()}
                </span>
              ))}
            </span>
            <SeloEstadoJob estado={e.estado} />
            <Icone nome="direita" tamanho={16} className="lista-linhas__seta" />
          </span>
        </li>
      ))}
    </ul>
  );
}
