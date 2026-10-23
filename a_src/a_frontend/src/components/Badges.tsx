import type { ReactNode } from 'react';
import type { Decisao, DecisaoHumana, EstadoCampo, EstadoJob, Nivel, Severidade } from '../api/types';
import {
  ICONE_DECISAO,
  ICONE_TOM,
  ROTULO_DECISAO,
  ROTULO_DECISAO_HUMANA,
  ROTULO_ESTADO_CAMPO,
  ROTULO_ESTADO_JOB,
  ROTULO_NIVEL,
  ROTULO_SEVERIDADE,
  TOM_DECISAO,
  TOM_DECISAO_HUMANA,
  TOM_ESTADO_CAMPO,
  TOM_ESTADO_JOB,
  TOM_NIVEL,
  TOM_SEVERIDADE,
  type Tom,
} from '../lib/labels';
import { Icone, type NomeIcone } from './Icon';

/** A cor nunca é o único sinal: todo selo tem texto (e, quando faz sentido, um ícone decorativo). */
export function Selo({ tom, icone, children }: { tom: Tom; icone?: NomeIcone; children: ReactNode }) {
  return (
    <span className={`selo selo--${tom}`}>
      {icone ? <Icone nome={icone} tamanho={13} /> : null}
      {children}
    </span>
  );
}

export const SeloDecisao = ({ decisao }: { decisao: Decisao }) => (
  <Selo tom={TOM_DECISAO[decisao]} icone={ICONE_DECISAO[decisao]}>
    {ROTULO_DECISAO[decisao]}
  </Selo>
);

export const SeloDecisaoHumana = ({ decisao }: { decisao: DecisaoHumana }) => (
  <Selo tom={TOM_DECISAO_HUMANA[decisao]} icone={ICONE_TOM[TOM_DECISAO_HUMANA[decisao]]}>
    {ROTULO_DECISAO_HUMANA[decisao]}
  </Selo>
);

export const SeloNivel = ({ nivel }: { nivel: Nivel }) => (
  <Selo tom={TOM_NIVEL[nivel]} icone={nivel === 'ALTA' ? undefined : ICONE_TOM[TOM_NIVEL[nivel]]}>
    {ROTULO_NIVEL[nivel]}
  </Selo>
);

export const SeloEstadoCampo = ({ estado }: { estado: EstadoCampo }) => (
  <Selo tom={TOM_ESTADO_CAMPO[estado]}>{ROTULO_ESTADO_CAMPO[estado]}</Selo>
);

export const SeloSeveridade = ({ severidade }: { severidade: Severidade }) => (
  <Selo tom={TOM_SEVERIDADE[severidade]} icone={ICONE_TOM[TOM_SEVERIDADE[severidade]]}>
    {ROTULO_SEVERIDADE[severidade]}
  </Selo>
);

export const SeloEstadoJob = ({ estado }: { estado: EstadoJob }) => (
  <Selo
    tom={TOM_ESTADO_JOB[estado]}
    icone={estado === 'CONCLUIDA' ? 'certo' : estado === 'FALHOU' ? 'erro' : 'relogio'}
  >
    {ROTULO_ESTADO_JOB[estado]}
  </Selo>
);
