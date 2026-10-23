import { Fragment, useId } from 'react';
import type { Catalogo, CampoSaida, RegistroSaida } from '../api/types';
import { textoDoValor } from '../lib/format';
import { GRUPOS_DE_CAMPOS, ROTULO_NATUREZA, rotuloDe, rotuloDoCampo } from '../lib/labels';
import { Icone } from './Icon';
import { SeloEstadoCampo, SeloNivel } from './Badges';

function DetalheDoCampo({ campo }: { campo: CampoSaida }) {
  const evidencia = campo.evidencia;
  const extras = Object.entries(campo.detalhe_valor ?? {});
  return (
    <div className="campo__detalhe">
      <dl>
        {campo.texto_literal ? (
          <>
            <dt>Trecho no documento</dt>
            <dd className="citacao">“{campo.texto_literal}”</dd>
          </>
        ) : null}
        {evidencia?.pagina ? (
          <>
            <dt>Onde está</dt>
            <dd>
              página {evidencia.pagina} · fonte: {evidencia.fonte} ·{' '}
              {evidencia.bbox ? 'posição disponível' : 'sem posição na página'}
            </dd>
          </>
        ) : null}
        {campo.natureza ? (
          <>
            <dt>Natureza</dt>
            <dd>{rotuloDe(ROTULO_NATUREZA, campo.natureza)}</dd>
          </>
        ) : null}
        <dt>Por que esta confiança</dt>
        <dd>
          <ul>
            {campo.confianca.motivos.map((motivo) => (
              <li key={motivo}>{motivo}</li>
            ))}
          </ul>
        </dd>
        {extras.map(([chave, valor]) => (
          <Fragment key={chave}>
            <dt>{chave}</dt>
            <dd>{valor}</dd>
          </Fragment>
        ))}
      </dl>
    </div>
  );
}

function ItemDeCampo({
  nome,
  campo,
  rotulo,
  selecionado,
  aoAlternar,
}: {
  nome: string;
  campo: CampoSaida;
  rotulo: string;
  selecionado: boolean;
  aoAlternar: () => void;
}) {
  const idDetalhe = useId();
  const mostraNivel = campo.estado !== 'NAO_APLICAVEL';
  return (
    <li
      className={selecionado ? 'campo campo--selecionado' : 'campo'}
      data-campo={nome}
      data-nivel={mostraNivel ? campo.confianca.nivel : undefined}
    >
      <button
        type="button"
        className="campo__cabecalho"
        aria-expanded={selecionado}
        aria-controls={idDetalhe}
        onClick={aoAlternar}
      >
        <span className="campo__rotulo">{rotulo}</span>
        <span className="campo__valor">{textoDoValor(nome, campo)}</span>
        <span className="campo__selos">
          {campo.estado !== 'EXTRAIDO' ? <SeloEstadoCampo estado={campo.estado} /> : null}
          {mostraNivel ? <SeloNivel nivel={campo.confianca.nivel} /> : null}
        </span>
        <Icone nome={selecionado ? 'baixo' : 'direita'} tamanho={16} className="campo__seta" />
      </button>
      <div id={idDetalhe} hidden={!selecionado}>
        {selecionado ? <DetalheDoCampo campo={campo} /> : null}
      </div>
    </li>
  );
}

/** Campos agrupados por assunto; escolher um campo mostra a evidência e o destaca na página. */
export function ListaCampos({
  registro,
  catalogo,
  selecionado,
  aoSelecionar,
}: {
  registro: RegistroSaida;
  catalogo: Catalogo | undefined;
  selecionado: string | null;
  aoSelecionar: (nome: string | null) => void;
}) {
  return (
    <div>
      {GRUPOS_DE_CAMPOS.map((grupo) => {
        const itens = grupo.campos.filter((c) => c in registro.campos);
        if (itens.length === 0) return null;
        return (
          <section key={grupo.titulo} className="grupo-campos" aria-label={grupo.titulo}>
            <h3>{grupo.titulo}</h3>
            <ul className="lista-simples">
              {itens.map((nome) => {
                const campo = registro.campos[nome];
                if (!campo) return null;
                return (
                  <ItemDeCampo
                    key={nome}
                    nome={nome}
                    campo={campo}
                    rotulo={rotuloDoCampo(catalogo, nome)}
                    selecionado={selecionado === nome}
                    aoAlternar={() => {
                      aoSelecionar(selecionado === nome ? null : nome);
                    }}
                  />
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
