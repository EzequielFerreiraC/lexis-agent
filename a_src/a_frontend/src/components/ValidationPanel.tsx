import { useState } from 'react';
import type { Catalogo, RegistroSaida } from '../api/types';
import { ehDicionario, paraTexto } from '../lib/record';
import { ROTULO_GOLDEN, TOM_GOLDEN, descricaoDaRegra, rotuloDe, rotuloDoCampo } from '../lib/labels';
import { Icone } from './Icon';
import { Selo, SeloSeveridade } from './Badges';

const ROTULO_COMPARACAO: Record<string, string> = {
  IGUAL: 'Confere',
  ATIVO: 'Emissor ativo',
  DIVERGE: 'Diverge',
  NAO_ENCONTRADO: 'Não encontrado',
  APONTA_PARA_OUTRO_REGISTRO: 'Aponta para outro registro',
};

function ComparacaoComBase({
  registro,
  catalogo,
}: {
  registro: RegistroSaida;
  catalogo: Catalogo | undefined;
}) {
  const golden = registro.validacao_golden;
  const comparacoes = (golden.comparacoes ?? []).filter(ehDicionario);
  return (
    <section aria-labelledby="titulo-golden" className="cartao">
      <div className="cartao__cabecalho">
        <h3 id="titulo-golden">
          <Icone nome="banco" tamanho={18} />
          Base de referência (golden records)
        </h3>
      </div>
      <p>
        <Selo tom={TOM_GOLDEN[golden.status] ?? 'neutro'}>{rotuloDe(ROTULO_GOLDEN, golden.status)}</Selo>
      </p>
      {golden.status === 'NOT_FOUND' ? (
        <p>
          Nenhum registro da base casa com o ISIN e o evento deste aviso.
          {golden.sugestao_por_nome ? ' Há um emissor de nome parecido; confira antes de cadastrar:' : null}
        </p>
      ) : null}
      {golden.sugestao_por_nome ? <p className="mono">{paraTexto(golden.sugestao_por_nome)}</p> : null}
      {comparacoes.length > 0 ? (
        // sem links dentro, a área de rolagem precisa de foco para rolar pelo teclado (axe: scrollable-region-focusable)
        <div
          className="tabela-rolavel"
          tabIndex={0}
          role="region"
          aria-label="Comparação com a base de referência"
        >
          <table className="tabela">
            <caption className="so-leitor">Comparação campo a campo com a base</caption>
            <thead>
              <tr>
                <th scope="col">Campo</th>
                <th scope="col">Extraído</th>
                <th scope="col">Base</th>
                <th scope="col">Resultado</th>
              </tr>
            </thead>
            <tbody>
              {comparacoes.map((linha, i) => {
                const campo = paraTexto(linha.campo);
                const resultado = paraTexto(linha.resultado);
                const confere = resultado === 'IGUAL' || resultado === 'ATIVO';
                return (
                  <tr key={`${campo}-${String(i)}`}>
                    <th scope="row">{rotuloDoCampo(catalogo, campo)}</th>
                    <td className="mono quebra">{paraTexto(linha.aviso)}</td>
                    <td className="mono quebra">{paraTexto(linha.golden)}</td>
                    <td>
                      <Selo tom={confere ? 'sucesso' : 'erro'} icone={confere ? 'certo' : 'erro'}>
                        {rotuloDe(ROTULO_COMPARACAO, resultado)}
                      </Selo>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

export function PainelValidacao({
  registro,
  catalogo,
}: {
  registro: RegistroSaida;
  catalogo: Catalogo | undefined;
}) {
  const [soFalhas, setSoFalhas] = useState(false);
  const regras = registro.regras.filter((r) => !soFalhas || r.resultado === 'FALHA');
  const falhas = registro.regras.filter((r) => r.resultado === 'FALHA').length;

  return (
    <div>
      <ComparacaoComBase registro={registro} catalogo={catalogo} />
      <section aria-labelledby="titulo-regras" className="cartao">
        <div className="linha linha--entre">
          <h3 id="titulo-regras">
            <Icone nome="escudo" tamanho={18} />
            Regras de coerência
          </h3>
          <label className="opcao">
            <input
              type="checkbox"
              checked={soFalhas}
              onChange={(e) => {
                setSoFalhas(e.target.checked);
              }}
            />
            Mostrar só o que não passou ({falhas})
          </label>
        </div>
        <ul className="lista-simples">
          {regras.map((regra) => (
            <li
              key={regra.id}
              className={`ficha ficha--${regra.resultado === 'OK' ? 'sucesso' : regra.resultado === 'FALHA' ? 'atencao' : 'neutro'}`}
            >
              <h4>
                {descricaoDaRegra(catalogo, regra.id)} <code>{regra.id}</code>
              </h4>
              <p>
                <SeloSeveridade severidade={regra.severidade} />{' '}
                {regra.resultado === 'OK' ? (
                  <Selo tom="sucesso" icone="certo">
                    Passou
                  </Selo>
                ) : regra.resultado === 'FALHA' ? (
                  <Selo tom="atencao" icone="alerta">
                    Não passou
                  </Selo>
                ) : (
                  <Selo tom="neutro">Não se aplica</Selo>
                )}
              </p>
              <p>{regra.detalhe}</p>
              {regra.esperado || regra.observado ? (
                <dl>
                  {regra.esperado ? (
                    <>
                      <dt>Esperado</dt>
                      <dd>{regra.esperado}</dd>
                    </>
                  ) : null}
                  {regra.observado ? (
                    <>
                      <dt>Observado</dt>
                      <dd>{regra.observado}</dd>
                    </>
                  ) : null}
                </dl>
              ) : null}
            </li>
          ))}
          {regras.length === 0 ? <li>Todas as regras avaliadas passaram.</li> : null}
        </ul>
      </section>
    </div>
  );
}
