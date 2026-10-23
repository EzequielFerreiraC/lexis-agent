import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ErroApi } from '../api/client';
import { Icone, type NomeIcone } from './Icon';

export function Carregando({ rotulo = 'Carregando…' }: { rotulo?: string }) {
  return (
    <>
      <p className="carregando" role="status">
        <span className="carregando__marca" aria-hidden="true" />
        {rotulo}
      </p>
      <div className="esqueleto" aria-hidden="true">
        <span className="esqueleto__linha" />
        <span className="esqueleto__linha" />
        <span className="esqueleto__linha" />
      </div>
    </>
  );
}

export function mensagemDoErro(erro: unknown): string {
  if (erro instanceof ErroApi) return erro.message;
  return erro instanceof Error ? 'Não foi possível falar com o servidor local.' : 'Erro desconhecido.';
}

const ICONE_AVISO: Record<'atencao' | 'info' | 'erro', NomeIcone> = {
  atencao: 'alerta',
  info: 'info',
  erro: 'erro',
};

export function CaixaErro({
  titulo = 'Algo deu errado',
  erro,
  aoTentarNovamente,
}: {
  titulo?: string;
  erro: unknown;
  aoTentarNovamente?: () => void;
}) {
  return (
    <div className="aviso aviso--erro" role="alert">
      <Icone nome="erro" tamanho={18} className="aviso__icone" />
      <div>
        <strong>{titulo}</strong>
        {mensagemDoErro(erro)}
        {aoTentarNovamente ? (
          <p>
            <button
              type="button"
              className="botao botao--secundario botao--pequeno"
              onClick={aoTentarNovamente}
            >
              Tentar novamente
            </button>
          </p>
        ) : null}
      </div>
    </div>
  );
}

export function Aviso({
  tom,
  titulo,
  children,
}: {
  tom: 'atencao' | 'info' | 'erro';
  titulo: string;
  children: ReactNode;
}) {
  return (
    <div className={`aviso aviso--${tom}`} role="note">
      <Icone nome={ICONE_AVISO[tom]} tamanho={18} className="aviso__icone" />
      <div>
        <strong>{titulo}</strong>
        {children}
      </div>
    </div>
  );
}

/** Estado vazio: diz o que falta e, quando houver, qual o próximo passo. */
export function Vazio({
  icone = 'pasta',
  titulo,
  children,
}: {
  icone?: NomeIcone;
  titulo: string;
  children?: ReactNode;
}) {
  return (
    <div className="vazio">
      <Icone nome={icone} tamanho={28} />
      <p className="vazio__titulo">{titulo}</p>
      {children ? <p className="vazio__texto">{children}</p> : null}
    </div>
  );
}

/** Banner que impede ler as métricas como acurácia de um modelo real. */
export function AvisoSimulado() {
  return (
    <Aviso tom="atencao" titulo="Extrações simuladas">
      As extrações desta execução vêm de gravações feitas manualmente, não de respostas reais do modelo. Elas
      validam a lógica determinística (evidência, regras, decisão), mas não medem a acurácia de um modelo.
      Para medir, rode com <strong>Extração com IA</strong>.
    </Aviso>
  );
}

/** Cabeçalho padrão de página: trilha de navegação, título, descrição e ações. */
export function CabecalhoPagina({
  trilha,
  titulo,
  meta,
  acoes,
  children,
}: {
  trilha?: { rotulo: string; para?: string }[];
  titulo: ReactNode;
  meta?: ReactNode;
  acoes?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="cabecalho-pagina">
      {trilha ? <TrilhaDePaginas itens={trilha} /> : null}
      <div className="cabecalho-pagina__linha">
        <div className="cabecalho-pagina__texto">
          <h1>{titulo}</h1>
          {meta ? <div className="cabecalho-pagina__meta">{meta}</div> : null}
        </div>
        {acoes ? <div className="cabecalho-pagina__acoes">{acoes}</div> : null}
      </div>
      {children}
    </header>
  );
}

function TrilhaDePaginas({ itens }: { itens: { rotulo: string; para?: string }[] }) {
  return (
    <nav aria-label="Você está em" className="trilha">
      <ol>
        {itens.map((item, i) => (
          <li key={`${item.rotulo}-${String(i)}`}>
            {item.para ? (
              <Link to={item.para}>{item.rotulo}</Link>
            ) : (
              <span aria-current="page">{item.rotulo}</span>
            )}
            {i < itens.length - 1 ? <Icone nome="direita" tamanho={14} className="trilha__sep" /> : null}
          </li>
        ))}
      </ol>
    </nav>
  );
}
