import { Fragment } from 'react';
import type { RegistroSaida } from '../api/types';
import { formatarDataHora, formatarDuracao, formatarUsd } from '../lib/format';
import { dicionario, lista, numero, paraTexto, texto } from '../lib/record';

/** Tudo o que permite reproduzir e auditar esta decisão: versões, entrada (sha256), chamadas ao modelo e às ferramentas. */
export function PainelAuditoria({ registro }: { registro: RegistroSaida }) {
  const a = registro.auditoria;
  const doc = registro.documento;
  const chamadasLlm = lista(a, 'chamadas_llm');
  const chamadasTools = lista(a, 'chamadas_de_tools');
  const avisos = Array.isArray(doc.avisos_ingestao) ? doc.avisos_ingestao.map(paraTexto) : [];

  return (
    <div>
      <section className="cartao" aria-labelledby="aud-doc">
        <h3 id="aud-doc">Documento e execução</h3>
        <dl className="campo__detalhe">
          <dt>Arquivo</dt>
          <dd>{texto(doc, 'arquivo') ?? '—'}</dd>
          <dt>SHA-256</dt>
          <dd className="mono quebra">{texto(doc, 'sha256') ?? '—'}</dd>
          <dt>Páginas</dt>
          <dd>{numero(doc, 'paginas') ?? '—'}</dd>
          <dt>Fonte do texto</dt>
          <dd>{texto(doc, 'fonte') ?? '—'}</dd>
          <dt>Modo</dt>
          <dd>{texto(a, 'modo') ?? '—'}</dd>
          <dt>Início</dt>
          <dd>{formatarDataHora(texto(a, 'iniciado_em'))}</dd>
          <dt>Fim</dt>
          <dd>{formatarDataHora(texto(a, 'concluido_em'))}</dd>
          <dt>Duração</dt>
          <dd>{formatarDuracao(numero(a, 'tempo_total_ms'))}</dd>
          <dt>Execução (run)</dt>
          <dd className="mono">{registro.run_id}</dd>
          <dt>Versão do contrato</dt>
          <dd>{registro.schema_version}</dd>
        </dl>
        {avisos.length > 0 ? <p className="nota">Avisos da leitura do PDF: {avisos.join('; ')}</p> : null}
      </section>

      <section className="cartao" aria-labelledby="aud-versoes">
        <h3 id="aud-versoes">Versões usadas</h3>
        <dl className="campo__detalhe">
          {Object.entries(registro.versoes).map(([chave, valor]) => (
            <Fragment key={chave}>
              <dt>{chave}</dt>
              <dd className="mono quebra">{valor}</dd>
            </Fragment>
          ))}
        </dl>
      </section>

      <section className="cartao" aria-labelledby="aud-custo">
        <h3 id="aud-custo">Modelo e custo</h3>
        <dl className="campo__detalhe">
          <dt>Chamadas à API</dt>
          <dd>{numero(a, 'chamadas_api') ?? 0}</dd>
          <dt>Reaproveitadas de gravação</dt>
          <dd>{numero(a, 'chamadas_cache') ?? 0}</dd>
          <dt>Tokens (entrada / saída)</dt>
          <dd>
            {numero(a, 'tokens_entrada') ?? 0} / {numero(a, 'tokens_saida') ?? 0}
          </dd>
          <dt>Reparos de contrato</dt>
          <dd>{numero(a, 'reparos_de_contrato') ?? 0}</dd>
          <dt>Custo estimado</dt>
          <dd>{formatarUsd(numero(a, 'custo_estimado_usd'))}</dd>
        </dl>
        <p className="nota">
          {texto(a, 'custo_fonte') ?? 'Custo estimado a partir de preços públicos de lista.'}
        </p>
        {chamadasLlm.length > 0 ? (
          <ul className="lista-simples">
            {chamadasLlm.map((c, i) => (
              <li key={i}>
                {paraTexto(c.etapa)} · {paraTexto(c.modelo)} · origem {paraTexto(c.origem)}
                {c.origem_fixture ? ` (${paraTexto(c.origem_fixture)})` : ''}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="cartao" aria-labelledby="aud-tools">
        <h3 id="aud-tools">Ferramentas determinísticas chamadas</h3>
        {chamadasTools.length === 0 ? (
          <p>Nenhuma.</p>
        ) : (
          <ul className="lista-simples">
            {chamadasTools.map((c, i) => {
              const resultado = dicionario(c, 'resultado');
              const falhas = Array.isArray(resultado.regras_falha)
                ? resultado.regras_falha.map(paraTexto)
                : [];
              return (
                <li key={i} className="ficha">
                  <h4>
                    <code>{paraTexto(c.tool)}</code> · origem {paraTexto(c.origem)} ·{' '}
                    {c.aceita === false ? 'recusada' : 'aceita'}
                  </h4>
                  <p>
                    Regras ok: {numero(resultado, 'regras_ok') ?? '—'} · não passaram:{' '}
                    {falhas.length ? falhas.join(', ') : 'nenhuma'}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
