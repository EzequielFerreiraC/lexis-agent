import type { Catalogo, Evidencia, Ficha } from '../api/types';
import { ROTULO_ACAO, rotuloDoCampo } from '../lib/labels';
import { Vazio } from './States';
import { Icone } from './Icon';

/** Fichas dizem o que conferir e onde, para o operador não reler o PDF inteiro. */
export function PainelConferencia({
  fichas,
  catalogo,
  aoVerNaPagina,
}: {
  fichas: Ficha[];
  catalogo: Catalogo | undefined;
  aoVerNaPagina: (campo: string, evidencia: Evidencia) => void;
}) {
  if (fichas.length === 0) {
    return (
      <Vazio icone="certo" titulo="Nada a conferir">
        Este documento não gerou fichas de conferência.
      </Vazio>
    );
  }
  return (
    <ul className="lista-simples">
      {fichas.map((ficha, i) => {
        const onde = ficha.onde_conferir;
        const rotuloCampo = ficha.campo ? rotuloDoCampo(catalogo, ficha.campo) : 'Documento';
        return (
          <li key={`${ficha.codigo}-${ficha.campo ?? ''}-${String(i)}`} className="ficha ficha--atencao">
            <h3>
              {ROTULO_ACAO[ficha.tipo_acao]} · {rotuloCampo}
            </h3>
            <p>
              <code className="codigo-chip">{ficha.codigo}</code>
            </p>
            <dl>
              <dt>O que fazer</dt>
              <dd>{ficha.acao_sugerida}</dd>
              {ficha.esperado ? (
                <>
                  <dt>Esperado</dt>
                  <dd>{ficha.esperado}</dd>
                </>
              ) : null}
              {ficha.observado ? (
                <>
                  <dt>Observado</dt>
                  <dd>{ficha.observado}</dd>
                </>
              ) : null}
              {onde?.trecho ? (
                <>
                  <dt>Onde conferir</dt>
                  <dd>
                    página {onde.pagina ?? '?'} — “{onde.trecho}”
                  </dd>
                </>
              ) : null}
            </dl>
            {onde?.pagina && ficha.campo ? (
              <button
                type="button"
                className="botao botao--secundario"
                onClick={() => {
                  aoVerNaPagina(ficha.campo ?? '', onde);
                }}
              >
                <Icone nome="busca" />
                Ver na página
              </button>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
