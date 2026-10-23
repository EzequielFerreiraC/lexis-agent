import { useId, useState, type SyntheticEvent } from 'react';
import { useRevisar, useSessao } from '../api/hooks';
import type { DecisaoHumana, RegistroSaida, RevisaoHumana } from '../api/types';
import { formatarDataHora } from '../lib/format';
import { ROTULO_DECISAO_HUMANA } from '../lib/labels';
import { DialogoConfirmacao } from './ConfirmDialog';
import { CaixaErro } from './States';
import { Icone } from './Icon';
import { SeloDecisaoHumana } from './Badges';

const MIN_JUSTIFICATIVA = 10; // o servidor confere de novo; aqui só evita um envio que ele recusaria

/**
 * Decisão do operador sobre um documento em revisão humana. O registro do pipeline nunca muda: a decisão fica ao
 * lado dele, com quem decidiu, quando, por quê e quais motivos foram conferidos. Uma decisão por execução.
 */
export function PainelRevisao({
  execucaoId,
  nome,
  registro,
  revisao,
}: {
  execucaoId: string;
  nome: string;
  registro: RegistroSaida;
  revisao: RevisaoHumana | null;
}) {
  if (registro.decisao.estado !== 'REVISAO_HUMANA') return null;
  return (
    <section className="cartao revisao" aria-labelledby="titulo-revisao">
      <h2 id="titulo-revisao">
        <Icone nome="bandeira" tamanho={18} />
        Decisão do operador
      </h2>
      {revisao ? (
        <RevisaoRegistrada revisao={revisao} />
      ) : (
        <FormularioRevisao execucaoId={execucaoId} nome={nome} registro={registro} />
      )}
    </section>
  );
}

function RevisaoRegistrada({ revisao }: { revisao: RevisaoHumana }) {
  return (
    <>
      <p>
        <SeloDecisaoHumana decisao={revisao.decisao} />
      </p>
      <dl className="revisao__dados">
        <dt>Operador</dt>
        <dd>{revisao.operador}</dd>
        <dt>Quando</dt>
        <dd>{formatarDataHora(revisao.revisada_em)}</dd>
        <dt>Justificativa</dt>
        <dd>{revisao.justificativa}</dd>
        <dt>Motivos conferidos</dt>
        <dd>
          {revisao.motivos_reconhecidos.length ? (
            <span className="chips">
              {revisao.motivos_reconhecidos.map((m) => (
                <code key={m} className="codigo-chip">
                  {m}
                </code>
              ))}
            </span>
          ) : (
            <span className="suave">nenhum</span>
          )}
        </dd>
        <dt>Registro revisado (sha256)</dt>
        <dd>
          <code className="quebra">{revisao.sha256_registro}</code>
        </dd>
      </dl>
      <p className="nota">
        A decisão automática continua no registro; esta decisão fica ao lado dele, nos arquivos da execução.
        Para decidir de novo, rode uma nova execução.
      </p>
    </>
  );
}

function FormularioRevisao({
  execucaoId,
  nome,
  registro,
}: {
  execucaoId: string;
  nome: string;
  registro: RegistroSaida;
}) {
  const revisar = useRevisar(execucaoId, nome);
  // com login, quem revisa é o usuário da sessão (o servidor ignora qualquer nome digitado)
  const usuario = useSessao().data?.usuario ?? null;
  const idOperador = useId();
  const idJustificativa = useId();
  const idNotaMotivos = useId();
  const [decisao, setDecisao] = useState<DecisaoHumana | null>(null);
  const [operador, setOperador] = useState('');
  const [justificativa, setJustificativa] = useState('');
  const [conferidos, setConferidos] = useState<Set<string>>(new Set());
  const [confirmando, setConfirmando] = useState(false);

  // um item por código: o mesmo motivo pode aparecer em mais de um campo
  const motivos = [...new Map(registro.decisao.motivos.map((m) => [m.codigo, m.mensagem])).entries()];
  const todosConferidos = motivos.every(([codigo]) => conferidos.has(codigo));
  const valido =
    decisao !== null &&
    (usuario !== null || operador.trim().length >= 2) &&
    justificativa.trim().length >= MIN_JUSTIFICATIVA &&
    (decisao === 'REJEITADO_NA_REVISAO' || todosConferidos);

  function aoEnviar(evento: SyntheticEvent) {
    evento.preventDefault();
    if (valido) setConfirmando(true);
  }

  function confirmar() {
    if (decisao === null) return;
    setConfirmando(false);
    revisar.mutate({
      decisao,
      operador: usuario ? null : operador,
      justificativa,
      motivos_reconhecidos: motivos.map(([codigo]) => codigo).filter((c) => conferidos.has(c)),
    });
  }

  return (
    <form onSubmit={aoEnviar} noValidate className="formulario">
      <fieldset className="campo-bloco">
        <legend className="rotulo">Motivos a conferir</legend>
        <p className="nota" id={idNotaMotivos}>
          Use as fichas da aba Conferência. Para aprovar, marque cada motivo depois de conferi-lo no
          documento.
        </p>
        {motivos.map(([codigo, mensagem]) => (
          <label key={codigo} className="opcao">
            <input
              type="checkbox"
              checked={conferidos.has(codigo)}
              aria-describedby={idNotaMotivos}
              onChange={(e) => {
                setConferidos((atual) => {
                  const proximo = new Set(atual);
                  if (e.target.checked) proximo.add(codigo);
                  else proximo.delete(codigo);
                  return proximo;
                });
              }}
            />
            <span>
              <code className="codigo-chip">{codigo}</code> {mensagem}
            </span>
          </label>
        ))}
      </fieldset>

      <fieldset className="campo-bloco">
        <legend className="rotulo">Decisão</legend>
        <div className="opcoes-cartao">
          {(['APROVADO_NA_REVISAO', 'REJEITADO_NA_REVISAO'] as const).map((d) => (
            <label key={d} className="opcao-cartao">
              <input
                type="radio"
                name="decisao-humana"
                value={d}
                checked={decisao === d}
                onChange={() => {
                  setDecisao(d);
                }}
              />
              <Icone
                nome={d === 'APROVADO_NA_REVISAO' ? 'certo' : 'erro'}
                tamanho={18}
                className="opcao-cartao__icone"
              />
              <span className="opcao-cartao__texto">{ROTULO_DECISAO_HUMANA[d]}</span>
            </label>
          ))}
        </div>
      </fieldset>

      {usuario ? (
        <p className="nota" role="status">
          Revisando como <strong>{usuario.nome}</strong> ({usuario.login}). A decisão fica registrada com este
          usuário.
        </p>
      ) : (
        <div className="campo-bloco">
          <label className="rotulo" htmlFor={idOperador}>
            Quem está revisando
          </label>
          <input
            id={idOperador}
            className="campo-texto"
            type="text"
            maxLength={80}
            autoComplete="name"
            value={operador}
            onChange={(e) => {
              setOperador(e.target.value);
            }}
          />
        </div>
      )}

      <div className="campo-bloco">
        <label className="rotulo" htmlFor={idJustificativa}>
          Justificativa (ao menos {MIN_JUSTIFICATIVA} caracteres)
        </label>
        <textarea
          id={idJustificativa}
          className="campo-texto revisao__justificativa"
          rows={3}
          maxLength={1000}
          value={justificativa}
          onChange={(e) => {
            setJustificativa(e.target.value);
          }}
        />
      </div>

      {decisao === 'APROVADO_NA_REVISAO' && !todosConferidos ? (
        <p className="nota" role="status">
          Para aprovar, marque todos os motivos como conferidos.
        </p>
      ) : null}

      <button type="submit" className="botao" disabled={!valido || revisar.isPending}>
        <Icone nome="certo" />
        {revisar.isPending ? 'Registrando…' : 'Registrar decisão'}
      </button>

      {revisar.isError ? <CaixaErro titulo="Decisão não registrada" erro={revisar.error} /> : null}

      <DialogoConfirmacao
        aberto={confirmando}
        titulo={decisao ? `${ROTULO_DECISAO_HUMANA[decisao]}?` : 'Registrar decisão?'}
        rotuloConfirmar="Registrar"
        perigo={decisao === 'REJEITADO_NA_REVISAO'}
        aoConfirmar={confirmar}
        aoCancelar={() => {
          setConfirmando(false);
        }}
      >
        <p>
          A decisão fica registrada com o seu nome e a justificativa, e não pode ser desfeita nesta execução.
          O registro do pipeline não é alterado.
        </p>
      </DialogoConfirmacao>
    </form>
  );
}
