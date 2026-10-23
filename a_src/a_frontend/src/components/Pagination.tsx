import { Icone } from './Icon';

/**
 * Navegação entre páginas: "Mostrando 21–40 de 57", anterior/próxima e a página atual. `pagina` começa em 1.
 * Os botões ficam desativados nas pontas (em vez de sumir), para o layout não pular.
 */
export function Paginacao({
  pagina,
  porPagina,
  total,
  carregando = false,
  aoMudar,
}: {
  pagina: number;
  porPagina: number;
  total: number;
  carregando?: boolean;
  aoMudar: (pagina: number) => void;
}) {
  const totalPaginas = Math.max(1, Math.ceil(total / porPagina));
  if (totalPaginas <= 1) return null;
  const inicio = (pagina - 1) * porPagina + 1;
  const fim = Math.min(pagina * porPagina, total);
  return (
    <nav className="paginacao" aria-label="Paginação">
      <p className="paginacao__resumo" aria-live="polite">
        Mostrando <strong>{inicio}</strong>–<strong>{fim}</strong> de <strong>{total}</strong>
      </p>
      <div className="paginacao__controles">
        <button
          type="button"
          className="botao botao--secundario botao--pequeno"
          disabled={pagina <= 1 || carregando}
          onClick={() => {
            aoMudar(pagina - 1);
          }}
        >
          <Icone nome="esquerda" tamanho={16} />
          Anterior
        </button>
        <span className="paginacao__atual">
          Página {pagina} de {totalPaginas}
        </span>
        <button
          type="button"
          className="botao botao--secundario botao--pequeno"
          disabled={pagina >= totalPaginas || carregando}
          onClick={() => {
            aoMudar(pagina + 1);
          }}
        >
          Próxima
          <Icone nome="direita" tamanho={16} />
        </button>
      </div>
    </nav>
  );
}
