import { useState, type SyntheticEvent } from 'react';
import { useConfiguracao, useGuardarChave, useRemoverChave } from '../api/hooks';
import type { Configuracao } from '../api/types';
import { CabecalhoPagina, CaixaErro, Carregando } from '../components/States';
import { Icone } from '../components/Icon';
import { useTituloDaPagina } from '../components/Layout';

const usd = (valor: number): string => valor.toLocaleString('pt-BR', { minimumFractionDigits: 2 });

function precoDoModelo(c: Configuracao): string {
  if (c.preco_entrada_usd_mtok == null || c.preco_saida_usd_mtok == null) return 'Preço não informado';
  return `US$ ${usd(c.preco_entrada_usd_mtok)} entrada · US$ ${usd(c.preco_saida_usd_mtok)} saída, por milhão de tokens`;
}

/** Só leitura: o modelo é configuração de deploy (LEXIS_MODEL). As gravações e a mutação só valem para o modelo avaliado. */
function SecaoModelo({ config }: { config: Configuracao }) {
  return (
    <fieldset className="cartao" aria-describedby="nota-modelo">
      <legend>
        <span className="passo">1</span>Modelo
      </legend>

      <p className="linha" role="status">
        Provedor: <strong>{config.provedor}</strong> · Modelo: <code>{config.modelo}</code>
      </p>
      <p className="nota">{precoDoModelo(config)}.</p>
      <p className="nota" id="nota-modelo">
        O modelo vem da configuração do servidor (<code>LEXIS_MODEL</code>) e não é trocado pelo console: as
        gravações do lote foram feitas com ele, e outro modelo precisaria ser avaliado antes. Ele é usado no
        modo <strong>Extração com IA</strong>; no modo <strong>Demonstração</strong> nenhum modelo é chamado.
        Preços são estimativas de lista, sem descontos de cache ou de lote.
      </p>
    </fieldset>
  );
}

const ORIGEM_DA_CHAVE = {
  tela: 'digitada aqui',
  ambiente: 'vem do ambiente do servidor (ANTHROPIC_API_KEY)',
};

function SecaoChave({ config }: { config: Configuracao }) {
  const guardar = useGuardarChave();
  const remover = useRemoverChave();
  const [chave, setChave] = useState('');
  const { configurada, origem, final } = config.chave;

  function aoEnviar(evento: SyntheticEvent) {
    evento.preventDefault();
    if (!chave.trim()) return;
    guardar.mutate(chave.trim(), {
      onSuccess: () => {
        setChave(''); // depois de enviada, a chave não fica na tela nem no estado do navegador
      },
    });
  }

  return (
    <fieldset className="cartao" aria-describedby="nota-chave">
      <legend>
        <span className="passo">2</span>Chave de API
      </legend>

      <p className="linha" role="status">
        <Icone nome={configurada ? 'certo' : 'alerta'} tamanho={18} className="opcao-cartao__icone" />
        {configurada && origem ? (
          <span>
            Chave configurada (termina em <code>{final}</code>), {ORIGEM_DA_CHAVE[origem]}.
          </span>
        ) : (
          <span>
            Nenhuma chave configurada. Os modos Replay e Automático com gravação continuam funcionando.
          </span>
        )}
      </p>

      <form onSubmit={aoEnviar} noValidate className="campo-bloco">
        <label className="rotulo" htmlFor="chave-api">
          {configurada ? 'Trocar a chave' : 'Chave de API da Anthropic'}
        </label>
        <div className="linha">
          <input
            id="chave-api"
            className="campo-texto"
            type="password"
            value={chave}
            onChange={(e) => {
              setChave(e.target.value);
            }}
            placeholder="sk-ant-…"
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
          />
          <button type="submit" className="botao" disabled={guardar.isPending || !chave.trim()}>
            <Icone nome="chave" />
            {guardar.isPending ? 'Guardando…' : 'Guardar chave'}
          </button>
        </div>
      </form>

      {guardar.isError ? <CaixaErro titulo="Chave não aceita" erro={guardar.error} /> : null}
      {remover.isError ? <CaixaErro titulo="Não foi possível remover a chave" erro={remover.error} /> : null}

      {origem === 'tela' ? (
        <p>
          <button
            type="button"
            className="botao botao--secundario botao--pequeno"
            disabled={remover.isPending}
            onClick={() => {
              remover.mutate(undefined);
            }}
          >
            Remover a chave digitada
          </button>
        </p>
      ) : null}

      <p className="nota" id="nota-chave">
        A chave fica só na memória do servidor local: não é gravada em disco, em log nem nos relatórios, e
        some quando o <code>lexis serve</code> reinicia. Depois de enviada, o console nunca a mostra de novo
        (só os 4 últimos caracteres). Ela é usada apenas para chamar a Anthropic no modo Extração com IA.
      </p>
    </fieldset>
  );
}

export function ConfiguracoesPagina() {
  useTituloDaPagina('Configurações');
  const consulta = useConfiguracao();

  return (
    <>
      <CabecalhoPagina titulo="Configurações">
        <p className="cabecalho-pagina__descricao">
          Veja o modelo que roda o pipeline e informe a chave de API. A chave digitada vale para este servidor
          local, até ele reiniciar.
        </p>
      </CabecalhoPagina>

      {consulta.isPending ? <Carregando /> : null}
      {consulta.isError ? (
        <CaixaErro erro={consulta.error} aoTentarNovamente={() => void consulta.refetch()} />
      ) : null}
      {consulta.data ? (
        <div className="formulario">
          <SecaoModelo config={consulta.data} />
          <SecaoChave config={consulta.data} />
        </div>
      ) : null}
    </>
  );
}
