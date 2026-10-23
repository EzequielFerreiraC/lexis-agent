import { useImagemPagina, usePaginaMeta } from '../api/hooks';
import type { Evidencia } from '../api/types';
import { CaixaErro, Carregando } from './States';
import { Icone } from './Icon';

export interface Destaque {
  rotulo: string;
  evidencia: Evidencia | null;
}

/** Posição do trecho em % da página: independe do tamanho em pixels da imagem. bbox = [x0, topo, x1, base] em pontos. */
export function caixaEmPorcentagem(
  bbox: number[] | null | undefined,
  larguraPt: number,
  alturaPt: number,
): { left: string; top: string; width: string; height: string } | null {
  if (bbox?.length !== 4 || larguraPt <= 0 || alturaPt <= 0) return null;
  const [x0, topo, x1, base] = bbox as [number, number, number, number];
  const pct = (valor: number, total: number) => `${((valor / total) * 100).toFixed(3)}%`;
  return {
    left: pct(x0, larguraPt),
    top: pct(topo, alturaPt),
    width: pct(x1 - x0, larguraPt),
    height: pct(base - topo, alturaPt),
  };
}

/**
 * A página é uma IMAGEM renderizada no servidor: o navegador nunca abre o PDF original (entrada não confiável,
 * pode ter conteúdo ativo). O destaque é um retângulo sobre a imagem.
 */
export function PaginaComDestaque({
  execucaoId,
  nome,
  numero,
  total,
  aoMudarPagina,
  destaque,
}: {
  execucaoId: string;
  nome: string;
  numero: number;
  total: number;
  aoMudarPagina: (numero: number) => void;
  destaque: Destaque | null;
}) {
  const meta = usePaginaMeta(execucaoId, nome, numero);
  const imagem = useImagemPagina(execucaoId, nome, numero);

  const evidencia = destaque?.evidencia ?? null;
  const naPagina = evidencia?.pagina === numero;
  const caixa =
    meta.data && naPagina
      ? caixaEmPorcentagem(evidencia.bbox, meta.data.largura_pt, meta.data.altura_pt)
      : null;

  let legenda: string | null = null;
  if (destaque) {
    if (!evidencia?.trecho)
      legenda = `“${destaque.rotulo}” não tem trecho no documento (valor ausente, derivado ou não se aplica).`;
    else if (evidencia.pagina !== numero)
      legenda = `“${destaque.rotulo}” está na página ${String(evidencia.pagina ?? '?')}.`;
    else if (!caixa)
      legenda = `“${destaque.rotulo}”: sem posição na página (fonte: ${evidencia.fonte}). Confira pelo trecho literal.`;
    else legenda = `Destacando “${destaque.rotulo}” na página ${String(numero)}.`;
  }

  if (imagem.erro || meta.isError)
    return <CaixaErro titulo="Não foi possível carregar a página" erro={meta.error ?? new Error()} />;

  return (
    <figure className="pagina-figura">
      {imagem.url ? (
        <div className="pagina-img">
          <img src={imagem.url} alt={`Página ${String(numero)} do documento ${nome}`} />
          {caixa ? (
            <div
              className="pagina-img__destaque"
              data-testid="destaque-bbox"
              style={caixa}
              aria-hidden="true"
            />
          ) : null}
        </div>
      ) : (
        <Carregando rotulo="Carregando a página…" />
      )}
      <figcaption>
        {total > 1 ? (
          <div className="pagina-nav">
            <button
              type="button"
              className="botao botao--secundario"
              disabled={numero <= 1}
              onClick={() => {
                aoMudarPagina(numero - 1);
              }}
            >
              <Icone nome="esquerda" />
              Página anterior
            </button>
            <span>
              Página {numero} de {total}
            </span>
            <button
              type="button"
              className="botao botao--secundario"
              disabled={numero >= total}
              onClick={() => {
                aoMudarPagina(numero + 1);
              }}
            >
              Próxima página
              <Icone nome="direita" />
            </button>
          </div>
        ) : null}
        <p className="nota pagina-legenda" role="status">
          <Icone nome="alvo" tamanho={14} />
          {legenda ?? 'Selecione um campo para ver onde ele está na página.'}
        </p>
      </figcaption>
    </figure>
  );
}
