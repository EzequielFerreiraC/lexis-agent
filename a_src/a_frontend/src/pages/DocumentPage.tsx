import * as Tabs from '@radix-ui/react-tabs';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useCatalogo, useExecucao, useRegistro } from '../api/hooks';
import type { Evidencia } from '../api/types';
import { CabecalhoPagina, CaixaErro, Carregando } from '../components/States';
import { Icone, type NomeIcone } from '../components/Icon';
import { useTituloDaPagina } from '../components/Layout';
import { Etapas } from '../components/Steps';
import { ListaCampos } from '../components/FieldList';
import { PaginaComDestaque } from '../components/HighlightedPage';
import { PainelAuditoria } from '../components/AuditPanel';
import { ParaAprovar } from '../components/ApprovalPath';
import { PainelConferencia } from '../components/ChecklistPanel';
import { PainelRevisao } from '../components/ReviewPanel';
import { PainelValidacao } from '../components/ValidationPanel';
import { SeloDecisao, SeloDecisaoHumana } from '../components/Badges';
import { numero, texto } from '../lib/record';
import { TOM_DECISAO, rotuloDoCampo } from '../lib/labels';

interface Selecao {
  campo: string;
  evidencia: Evidencia | null;
}

function Aba({ valor, icone, children }: { valor: string; icone: NomeIcone; children: React.ReactNode }) {
  return (
    <Tabs.Trigger className="abas__gatilho" value={valor}>
      <Icone nome={icone} tamanho={16} />
      {children}
    </Tabs.Trigger>
  );
}

export function DocumentoPagina() {
  const { id = '', nome = '' } = useParams();
  useTituloDaPagina(nome);
  const consulta = useRegistro(id, nome);
  const execucao = useExecucao(id);
  const catalogo = useCatalogo();
  const [pagina, setPagina] = useState(1);
  const [selecao, setSelecao] = useState<Selecao | null>(null);
  const [aba, setAba] = useState('campos');

  if (consulta.isPending) return <Carregando rotulo="Carregando o documento…" />;
  if (consulta.isError) {
    return (
      <CaixaErro
        titulo="Documento não encontrado"
        erro={consulta.error}
        aoTentarNovamente={() => void consulta.refetch()}
      />
    );
  }
  const registro = consulta.data;
  const totalPaginas = Math.max(1, numero(registro.documento, 'paginas') ?? 1);
  const tipo = texto(registro.evento, 'tipo');
  const infoTipo = tipo ? catalogo.data?.tipos[tipo] : undefined;
  const fichas = registro.fichas_conferencia.length;
  const tomDecisao = TOM_DECISAO[registro.decisao.estado];
  // a decisão humana vem do resumo da execução; sem ele, o formulário não aparece (não sabemos se já houve decisão)
  const resumo = execucao.data?.documentos?.find((d) => d.arquivo === nome);

  function selecionar(campo: string, evidencia: Evidencia | null) {
    setSelecao({ campo, evidencia });
    if (evidencia?.pagina) setPagina(Math.min(evidencia.pagina, totalPaginas));
  }

  const destaque = selecao
    ? { rotulo: rotuloDoCampo(catalogo.data, selecao.campo), evidencia: selecao.evidencia }
    : null;

  return (
    <>
      <Etapas atual={3} />
      <CabecalhoPagina
        trilha={[
          { rotulo: 'Histórico', para: '/historico' },
          { rotulo: `Execução ${id}`, para: `/execucoes/${id}` },
          { rotulo: nome },
        ]}
        titulo={nome}
        meta={
          <>
            {infoTipo ? <span>{infoTipo.rotulo}</span> : null}
            <span>
              {totalPaginas} página{totalPaginas > 1 ? 's' : ''}
            </span>
          </>
        }
      />

      <div className="detalhe">
        <div className="detalhe__pagina">
          <PaginaComDestaque
            execucaoId={id}
            nome={nome}
            numero={pagina}
            total={totalPaginas}
            aoMudarPagina={setPagina}
            destaque={destaque}
          />
        </div>

        <div className="detalhe__conteudo">
          <section className={`decisao decisao--${tomDecisao}`} aria-labelledby="titulo-decisao">
            <h2 id="titulo-decisao" className="linha">
              <SeloDecisao decisao={registro.decisao.estado} />
              {resumo?.revisao ? <SeloDecisaoHumana decisao={resumo.revisao.decisao} /> : null}
            </h2>
            <p className="decisao__resumo">{registro.decisao.resumo}</p>
            <p className="nota">Linha da tabela de decisão: {registro.decisao.linha_da_tabela}</p>
            {registro.decisao.motivos.length > 0 ? (
              <ul className="lista-simples decisao__motivos">
                {registro.decisao.motivos.map((m, i) => (
                  <li key={`${m.codigo}-${m.campo ?? ''}-${String(i)}`}>
                    <code className="codigo-chip">{m.codigo}</code>{' '}
                    {m.campo ? `(${rotuloDoCampo(catalogo.data, m.campo)}) ` : ''}— {m.mensagem}
                  </li>
                ))}
              </ul>
            ) : null}
            {registro.decisao.para_aprovar ? (
              <ParaAprovar dados={registro.decisao.para_aprovar} catalogo={catalogo.data} />
            ) : null}
            {infoTipo ? (
              <p className="nota">
                Tipo: {infoTipo.rotulo}. Tratamento tributário: {infoTipo.tratamento_tributario}.
              </p>
            ) : null}
          </section>

          {resumo ? (
            <PainelRevisao execucaoId={id} nome={nome} registro={registro} revisao={resumo.revisao ?? null} />
          ) : null}
          {execucao.isError ? (
            <CaixaErro titulo="Não foi possível carregar a decisão do operador" erro={execucao.error} />
          ) : null}

          <Tabs.Root value={aba} onValueChange={setAba}>
            <Tabs.List className="abas__lista" aria-label="Detalhes do documento">
              <Aba valor="campos" icone="lista">
                Campos
              </Aba>
              <Aba valor="validacao" icone="escudo">
                Validação
              </Aba>
              <Aba valor="conferencia" icone="bandeira">
                Conferência ({fichas})
              </Aba>
              <Aba valor="auditoria" icone="historico">
                Auditoria
              </Aba>
            </Tabs.List>
            <Tabs.Content value="campos">
              <ListaCampos
                registro={registro}
                catalogo={catalogo.data}
                selecionado={selecao?.campo ?? null}
                aoSelecionar={(campo) => {
                  if (campo === null) setSelecao(null);
                  else selecionar(campo, registro.campos[campo]?.evidencia ?? null);
                }}
              />
            </Tabs.Content>
            <Tabs.Content value="validacao">
              <PainelValidacao registro={registro} catalogo={catalogo.data} />
            </Tabs.Content>
            <Tabs.Content value="conferencia">
              <PainelConferencia
                fichas={registro.fichas_conferencia}
                catalogo={catalogo.data}
                aoVerNaPagina={(campo, evidencia) => {
                  selecionar(campo, evidencia);
                }}
              />
            </Tabs.Content>
            <Tabs.Content value="auditoria">
              <PainelAuditoria registro={registro} />
            </Tabs.Content>
          </Tabs.Root>
        </div>
      </div>
    </>
  );
}
