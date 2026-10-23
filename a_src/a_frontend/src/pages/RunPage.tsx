import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useExecucao } from '../api/hooks';
import { api } from '../api/client';
import { RELATORIOS, type Decisao, type NomeRelatorio } from '../api/types';
import {
  Aviso,
  AvisoSimulado,
  CabecalhoPagina,
  CaixaErro,
  Carregando,
  mensagemDoErro,
} from '../components/States';
import { Icone } from '../components/Icon';
import { useTituloDaPagina } from '../components/Layout';
import { SeloEstadoJob } from '../components/Badges';
import { Etapas } from '../components/Steps';
import { TabelaDocumentos } from '../components/DocumentTable';
import { formatarDataHora } from '../lib/format';
import { DECISOES, ICONE_DECISAO, ROTULO_DECISAO, ROTULO_MODO, TOM_DECISAO } from '../lib/labels';

const DESCRICAO_RELATORIO: Record<NomeRelatorio, string> = {
  'relatorio_excecoes.md': 'Relatório de exceções (legível)',
  'relatorio_excecoes.json': 'Relatório de exceções (JSON)',
  'resumo_execucao.json': 'Resumo da execução (JSON)',
  'auditoria.jsonl': 'Trilha de auditoria (JSONL)',
};

/** O download passa pela API com o token, então o arquivo é buscado como Blob e salvo localmente. */
async function baixar(id: string, arquivo: NomeRelatorio): Promise<void> {
  const blob = await api.relatorio(id, arquivo);
  const url = URL.createObjectURL(blob);
  const ancora = document.createElement('a');
  ancora.href = url;
  ancora.download = arquivo;
  ancora.click();
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 1000);
}

function Relatorios({ id }: { id: string }) {
  const [erro, setErro] = useState<string | null>(null);
  return (
    <section className="cartao" aria-labelledby="titulo-relatorios">
      <div className="cartao__cabecalho">
        <h2 id="titulo-relatorios">
          <Icone nome="baixar" tamanho={18} />
          Relatórios para baixar
        </h2>
      </div>
      <ul className="lista-simples lista-simples--linha">
        {RELATORIOS.map((arquivo) => (
          <li key={arquivo}>
            <button
              type="button"
              className="botao botao--secundario"
              onClick={() => {
                setErro(null);
                baixar(id, arquivo).catch((e: unknown) => {
                  setErro(mensagemDoErro(e));
                });
              }}
            >
              <Icone nome="baixar" />
              {DESCRICAO_RELATORIO[arquivo]}
            </button>
          </li>
        ))}
      </ul>
      {erro ? (
        <p role="alert" className="aviso aviso--erro">
          <Icone nome="erro" tamanho={18} className="aviso__icone" />
          <span>{erro}</span>
        </p>
      ) : null}
    </section>
  );
}

export function ExecucaoPagina() {
  const { id = '' } = useParams();
  const consulta = useExecucao(id);
  const execucao = consulta.data;
  const [filtro, setFiltro] = useState<Decisao | 'TODAS'>('TODAS');
  useTituloDaPagina(`Execução ${id}`);

  if (consulta.isPending) return <Carregando rotulo="Carregando a execução…" />;
  if (consulta.isError || !execucao) {
    return (
      <CaixaErro
        titulo="Execução não encontrada"
        erro={consulta.error}
        aoTentarNovamente={() => void consulta.refetch()}
      />
    );
  }

  const andando = execucao.estado === 'NA_FILA' || execucao.estado === 'EM_ANDAMENTO';
  const percentual = execucao.total > 0 ? Math.round((execucao.concluidos / execucao.total) * 100) : 0;

  return (
    <>
      <Etapas atual={andando || execucao.estado === 'FALHOU' ? 2 : 3} falhou={execucao.estado === 'FALHOU'} />
      <CabecalhoPagina
        trilha={[{ rotulo: 'Histórico', para: '/historico' }, { rotulo: `Execução ${execucao.id}` }]}
        titulo={`Execução ${execucao.id}`}
        meta={
          <>
            <SeloEstadoJob estado={execucao.estado} />
            <span>iniciada em {formatarDataHora(execucao.criada_em)}</span>
            <span>modo {ROTULO_MODO[execucao.modo]}</span>
            {execucao.sem_ocr ? <span>sem OCR</span> : null}
          </>
        }
      />

      {execucao.extracoes_simuladas ? <AvisoSimulado /> : null}

      {andando ? (
        <section className="cartao" aria-label="Progresso">
          <div className="linha linha--entre">
            <label htmlFor="progresso">
              Processando {execucao.concluidos} de {execucao.total} documento(s)
            </label>
            <strong>{percentual}%</strong>
          </div>
          <progress id="progresso" max={execucao.total} value={execucao.concluidos} />
          <p role="status" className="nota">
            {execucao.estado === 'NA_FILA' ? 'Na fila, aguardando a execução anterior.' : 'Em andamento…'}
          </p>
        </section>
      ) : null}

      {execucao.estado === 'FALHOU' ? (
        <Aviso tom="erro" titulo="A execução falhou">
          {execucao.erro ?? 'Erro não informado.'}
        </Aviso>
      ) : null}

      <div className="contadores" role="group" aria-label="Documentos por decisão">
        {DECISOES.map((decisao: Decisao) => {
          const ativo = filtro === decisao;
          return (
            <button
              key={decisao}
              type="button"
              className={`contador contador--${TOM_DECISAO[decisao]}`}
              aria-pressed={ativo}
              title={ativo ? 'Mostrar todos os documentos' : `Filtrar a tabela: ${ROTULO_DECISAO[decisao]}`}
              onClick={() => {
                setFiltro(ativo ? 'TODAS' : decisao);
              }}
            >
              <span className="contador__icone">
                <Icone nome={ICONE_DECISAO[decisao]} tamanho={18} />
              </span>
              <span className="contador__numero">{execucao.contagem[decisao] ?? 0}</span>
              <span className="contador__rotulo">{ROTULO_DECISAO[decisao]}</span>
            </button>
          );
        })}
      </div>

      {execucao.documentos && execucao.documentos.length > 0 ? (
        <TabelaDocumentos
          execucaoId={execucao.id}
          documentos={execucao.documentos}
          filtro={filtro}
          aoMudarFiltro={setFiltro}
        />
      ) : null}

      {execucao.estado === 'CONCLUIDA' ? <Relatorios id={execucao.id} /> : null}
    </>
  );
}
