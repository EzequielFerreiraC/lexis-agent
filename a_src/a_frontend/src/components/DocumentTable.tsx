import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { Decisao, DocumentoResumo } from '../api/types';
import { formatarDuracao, formatarUsd } from '../lib/format';
import {
  DECISOES,
  PRIORIDADE_DECISAO,
  ROTULO_DECISAO,
  ROTULO_DISPOSICAO,
  ROTULO_GOLDEN,
  ROTULO_NIVEL,
  TOM_GOLDEN,
  rotuloDe,
} from '../lib/labels';
import { Vazio } from './States';
import { Icone } from './Icon';
import { Selo, SeloDecisao, SeloDecisaoHumana } from './Badges';

export function TabelaDocumentos({
  execucaoId,
  documentos,
  filtro,
  aoMudarFiltro,
}: {
  execucaoId: string;
  documentos: DocumentoResumo[];
  filtro: Decisao | 'TODAS';
  aoMudarFiltro: (filtro: Decisao | 'TODAS') => void;
}) {
  const [busca, setBusca] = useState('');

  const linhas = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    return documentos
      .filter((d) => filtro === 'TODAS' || d.estado === filtro)
      .filter((d) => termo === '' || d.arquivo.toLowerCase().includes(termo))
      .sort(
        (a, b) =>
          PRIORIDADE_DECISAO[a.estado] - PRIORIDADE_DECISAO[b.estado] || a.arquivo.localeCompare(b.arquivo),
      );
  }, [documentos, filtro, busca]);

  const filtrando = filtro !== 'TODAS' || busca.trim() !== '';

  return (
    <section aria-labelledby="titulo-documentos" className="cartao cartao--tabela">
      <div className="cartao__cabecalho cartao__cabecalho--ferramentas">
        <h2 id="titulo-documentos">
          <Icone nome="lista" tamanho={18} />
          Documentos <span className="contagem-titulo">{linhas.length}</span>
        </h2>
        <div className="ferramentas">
          <div className="campo-com-icone">
            <Icone nome="busca" tamanho={16} />
            <label className="so-leitor" htmlFor="busca-documento">
              Buscar documento
            </label>
            <input
              id="busca-documento"
              className="campo-texto"
              type="search"
              placeholder="Buscar pelo nome…"
              value={busca}
              onChange={(e) => {
                setBusca(e.target.value);
              }}
            />
          </div>
          <div className="campo-com-icone">
            <Icone nome="filtro" tamanho={16} />
            <label className="so-leitor" htmlFor="filtro-decisao">
              Filtrar por decisão
            </label>
            <select
              id="filtro-decisao"
              className="campo-texto"
              value={filtro}
              onChange={(e) => {
                aoMudarFiltro(e.target.value as Decisao | 'TODAS');
              }}
            >
              <option value="TODAS">Todas as decisões</option>
              {DECISOES.map((d) => (
                <option key={d} value={d}>
                  {ROTULO_DECISAO[d]}
                </option>
              ))}
            </select>
          </div>
          {filtrando ? (
            <button
              type="button"
              className="botao botao--texto botao--pequeno"
              onClick={() => {
                setBusca('');
                aoMudarFiltro('TODAS');
              }}
            >
              <Icone nome="limpar" tamanho={14} />
              Limpar filtros
            </button>
          ) : null}
        </div>
      </div>
      <p className="nota cartao__nota">O que exige atuação humana aparece primeiro.</p>
      <div className="tabela-rolavel">
        <table className="tabela">
          <caption className="so-leitor">
            Documentos processados, do que exige mais atenção ao que exige menos
          </caption>
          <thead>
            <tr>
              <th scope="col">Documento</th>
              <th scope="col">Decisão</th>
              <th scope="col">Tipo</th>
              <th scope="col">Base de referência</th>
              <th scope="col">Confiança mínima</th>
              <th scope="col">Motivos</th>
              <th scope="col" className="num">
                Tempo
              </th>
              <th scope="col" className="num">
                Custo estimado
              </th>
            </tr>
          </thead>
          <tbody>
            {linhas.map((d) => (
              <tr key={d.arquivo}>
                <th scope="row" className="quebra celula-documento">
                  <Link to={`/execucoes/${execucaoId}/documentos/${encodeURIComponent(d.arquivo)}`}>
                    <Icone nome="arquivo" tamanho={16} />
                    {d.arquivo}
                  </Link>
                  {d.fonte === 'SCAN' ? (
                    <>
                      {' '}
                      <Selo tom="info">Scan</Selo>
                    </>
                  ) : null}
                  {d.disposicao !== 'PROCESSADO' ? (
                    <div className="nota">{rotuloDe(ROTULO_DISPOSICAO, d.disposicao)}</div>
                  ) : null}
                </th>
                <td>
                  <span className="chips">
                    <SeloDecisao decisao={d.estado} />
                    {d.revisao ? <SeloDecisaoHumana decisao={d.revisao.decisao} /> : null}
                  </span>
                </td>
                <td>{d.tipo ?? '—'}</td>
                <td>
                  <Selo tom={TOM_GOLDEN[d.golden] ?? 'neutro'}>{rotuloDe(ROTULO_GOLDEN, d.golden)}</Selo>
                </td>
                <td>{d.confianca_minima ? rotuloDe(ROTULO_NIVEL, d.confianca_minima) : '—'}</td>
                <td className="quebra">
                  {d.motivos.length ? (
                    <span className="chips">
                      {d.motivos.map((m) => (
                        <code key={m} className="codigo-chip">
                          {m}
                        </code>
                      ))}
                    </span>
                  ) : (
                    <span className="suave">nenhum</span>
                  )}
                </td>
                <td className="num">{formatarDuracao(d.tempo_ms)}</td>
                <td className="num">{formatarUsd(d.custo_estimado_usd)}</td>
              </tr>
            ))}
            {linhas.length === 0 ? (
              <tr>
                <td colSpan={8}>
                  <Vazio icone="busca" titulo="Nenhum documento com esse filtro">
                    Ajuste a busca ou limpe os filtros para ver todos.
                  </Vazio>
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}
