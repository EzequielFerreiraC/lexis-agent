import { Link, useSearchParams } from 'react-router-dom';
import { useExecucoes } from '../api/hooks';
import { CabecalhoPagina, CaixaErro, Carregando, Vazio } from '../components/States';
import { Icone } from '../components/Icon';
import { useTituloDaPagina } from '../components/Layout';
import { ListaExecucoes } from '../components/RunList';
import { Paginacao } from '../components/Pagination';

export const POR_PAGINA = 20;

/** Lê `?pagina=` da URL: o número da página sobrevive ao recarregar, ao voltar e a um link compartilhado. */
function paginaDaUrl(parametros: URLSearchParams): number {
  const n = Number(parametros.get('pagina'));
  return Number.isInteger(n) && n >= 1 ? n : 1;
}

export function HistoricoPagina() {
  useTituloDaPagina('Histórico');
  const [parametros, setParametros] = useSearchParams();
  const pagina = paginaDaUrl(parametros);
  const consulta = useExecucoes(POR_PAGINA, (pagina - 1) * POR_PAGINA);
  const dados = consulta.data;

  function irPara(nova: number) {
    setParametros(nova > 1 ? { pagina: String(nova) } : {});
    window.scrollTo({ top: 0 });
  }

  return (
    <>
      <CabecalhoPagina titulo="Histórico">
        <p className="cabecalho-pagina__descricao">
          Todas as execuções, das mais recentes para as mais antigas. Abra uma para ver os documentos, a
          decisão de cada um e os relatórios.
        </p>
      </CabecalhoPagina>

      <section className="cartao" aria-labelledby="titulo-execucoes" aria-busy={consulta.isFetching}>
        <div className="cartao__cabecalho">
          <h2 id="titulo-execucoes">
            <Icone nome="historico" tamanho={18} />
            Execuções
            {dados ? <span className="contagem-titulo">{dados.total}</span> : null}
          </h2>
        </div>
        {consulta.isPending ? <Carregando /> : null}
        {consulta.isError ? (
          <CaixaErro erro={consulta.error} aoTentarNovamente={() => void consulta.refetch()} />
        ) : null}
        {dados && dados.total === 0 ? (
          <Vazio titulo="Nenhuma execução ainda">
            <Link to="/">Envie os primeiros documentos</Link> para começar.
          </Vazio>
        ) : null}
        {dados && dados.total > 0 && dados.itens.length === 0 ? (
          <Vazio titulo="Esta página não existe">
            <button
              type="button"
              className="botao botao--texto"
              onClick={() => {
                irPara(1);
              }}
            >
              Voltar para a primeira página
            </button>
          </Vazio>
        ) : null}
        {dados && dados.itens.length > 0 ? <ListaExecucoes itens={dados.itens} /> : null}
        {dados ? (
          <Paginacao
            pagina={pagina}
            porPagina={POR_PAGINA}
            total={dados.total}
            carregando={consulta.isPlaceholderData}
            aoMudar={irPara}
          />
        ) : null}
      </section>
    </>
  );
}
