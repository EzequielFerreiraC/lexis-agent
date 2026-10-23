import { Icone } from './Icon';

export const ETAPAS = ['Documentos', 'Modo de leitura', 'Processamento', 'Revisão'] as const;

/**
 * Passo a passo horizontal do fluxo, do envio à revisão. `atual` é o índice em `ETAPAS`; as anteriores contam
 * como concluídas. Só as etapas concluídas com `aoVoltar` viram botão (voltar dentro do assistente).
 */
export function Etapas({
  atual,
  falhou = false,
  aoVoltar,
}: {
  atual: number;
  falhou?: boolean;
  aoVoltar?: (indice: number) => void;
}) {
  return (
    <nav className="etapas" aria-label="Etapas">
      <ol className="etapas__lista">
        {ETAPAS.map((rotulo, i) => {
          const estado = i < atual ? 'feita' : i === atual ? (falhou ? 'falhou' : 'atual') : 'proxima';
          const marcador = (
            <>
              <span className="etapas__marcador" aria-hidden="true">
                {estado === 'feita' ? (
                  <Icone nome="certo" tamanho={16} />
                ) : estado === 'falhou' ? (
                  <Icone nome="erro" tamanho={16} />
                ) : (
                  i + 1
                )}
              </span>
              <span className="etapas__rotulo">
                {rotulo}
                {estado === 'feita' ? <span className="visualmente-oculto"> (concluída)</span> : null}
                {estado === 'falhou' ? <span className="visualmente-oculto"> (falhou)</span> : null}
              </span>
            </>
          );
          return (
            <li
              key={rotulo}
              className={`etapas__item etapas__item--${estado}`}
              aria-current={i === atual ? 'step' : undefined}
            >
              {estado === 'feita' && aoVoltar ? (
                <button
                  type="button"
                  className="etapas__alvo etapas__alvo--botao"
                  onClick={() => {
                    aoVoltar(i);
                  }}
                >
                  {marcador}
                </button>
              ) : (
                <span className="etapas__alvo">{marcador}</span>
              )}
            </li>
          );
        })}
      </ol>
      <p className="etapas__legenda" aria-hidden="true">
        Etapa {atual + 1} de {ETAPAS.length} · {ETAPAS[atual]}
      </p>
    </nav>
  );
}
