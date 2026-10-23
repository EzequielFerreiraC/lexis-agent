import { useEffect, useRef, useState, type SyntheticEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useExecucoes, useIniciarExecucao, useSaude } from '../api/hooks';
import type { Modo } from '../api/types';
import { CabecalhoPagina, CaixaErro, Carregando, Vazio } from '../components/States';
import { DialogoConfirmacao } from '../components/ConfirmDialog';
import { Icone } from '../components/Icon';
import { useTituloDaPagina } from '../components/Layout';
import { ListaExecucoes } from '../components/RunList';
import { Etapas } from '../components/Steps';
import { formatarBytes } from '../lib/format';
import { ICONE_MODO, ROTULO_MODO } from '../lib/labels';

/** A tela oferece dois modos: sem chave (demonstração, só gravações) e com chave (o modelo lê cada documento). */
type ModoDaTela = Extract<Modo, 'replay' | 'live'>;
type Passo = 0 | 1;

const RECENTES = 5;

function ExecucoesRecentes() {
  const consulta = useExecucoes(RECENTES);
  const dados = consulta.data;
  return (
    <section className="cartao" aria-labelledby="titulo-recentes">
      <div className="cartao__cabecalho">
        <h2 id="titulo-recentes">
          <Icone nome="historico" tamanho={18} />
          Execuções recentes
        </h2>
        {dados && dados.total > RECENTES ? (
          <Link className="cartao__acao" to="/historico">
            Ver todas ({dados.total})
            <Icone nome="direita" tamanho={16} />
          </Link>
        ) : null}
      </div>
      {consulta.isPending ? <Carregando /> : null}
      {consulta.isError ? (
        <CaixaErro erro={consulta.error} aoTentarNovamente={() => void consulta.refetch()} />
      ) : null}
      {dados?.total === 0 ? (
        <Vazio titulo="Nenhuma execução ainda">Envie os PDFs acima e siga as etapas.</Vazio>
      ) : null}
      {dados && dados.itens.length > 0 ? <ListaExecucoes itens={dados.itens} /> : null}
    </section>
  );
}

export function ExecutarPagina() {
  useTituloDaPagina('Executar');
  const navegar = useNavigate();
  const saude = useSaude();
  const iniciar = useIniciarExecucao();

  const [passo, setPasso] = useState<Passo>(0);
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [modoEscolhido, setModoEscolhido] = useState<ModoDaTela | null>(null);
  const [semOcr, setSemOcr] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [erroLocal, setErroLocal] = useState<string | null>(null);
  const etapa = useRef<HTMLFieldSetElement>(null);
  const primeiroPasso = useRef(true);

  useEffect(() => {
    if (primeiroPasso.current) {
      primeiroPasso.current = false;
      return;
    }
    window.scrollTo({ top: 0 }); // o passo a passo fica à vista
    etapa.current?.focus({ preventScroll: true }); // o botão que trocou de etapa some: o foco vai para a etapa nova
  }, [passo]);

  const limites = saude.data?.limites;
  const infoIa = saude.data?.modos.find((m) => m.id === 'live');
  const iaDisponivel = infoIa?.disponivel ?? false;
  // sem escolha explícita, quem tem chave começa na extração com IA; quem não tem, na demonstração
  const modo: ModoDaTela = modoEscolhido ?? (iaDisponivel ? 'live' : 'replay');

  function validarArquivos(): string | null {
    if (arquivos.length === 0) return 'Escolha ao menos um arquivo PDF.';
    if (limites && arquivos.length > limites.max_arquivos)
      return `No máximo ${String(limites.max_arquivos)} arquivos por envio.`;
    const grande = limites ? arquivos.find((a) => a.size > limites.max_bytes_por_arquivo) : undefined;
    if (grande && limites)
      return `“${grande.name}” passa do limite de ${formatarBytes(limites.max_bytes_por_arquivo)}.`;
    const naoPdf = arquivos.find((a) => !a.name.toLowerCase().endsWith('.pdf'));
    return naoPdf ? `“${naoPdf.name}” não é um PDF.` : null;
  }

  function adicionar(novos: File[]) {
    setErroLocal(null);
    setArquivos((atuais) => {
      const nomes = new Set(novos.map((a) => a.name));
      return [...atuais.filter((a) => !nomes.has(a.name)), ...novos]; // reenviar o mesmo nome substitui
    });
  }

  function enviar(confirmarLive: boolean) {
    iniciar.mutate(
      {
        origem: 'upload',
        modo,
        sem_ocr: semOcr,
        confirmar_live: confirmarLive,
        arquivos: null,
        arquivosParaEnviar: arquivos,
      },
      { onSuccess: (execucao) => void navegar(`/execucoes/${execucao.id}`) },
    );
  }

  function aoEnviar(evento: SyntheticEvent) {
    evento.preventDefault();
    const problema = validarArquivos();
    setErroLocal(problema);
    if (problema) {
      setPasso(0);
      return;
    }
    if (passo === 0) {
      setPasso(1);
      return;
    }
    if (modo === 'live') setConfirmando(true);
    else enviar(false);
  }

  return (
    <>
      <Etapas
        atual={passo}
        aoVoltar={(i) => {
          setPasso(i as Passo);
        }}
      />

      <CabecalhoPagina titulo="Nova execução">
        <p className="cabecalho-pagina__descricao">
          Envie os avisos em PDF e escolha como eles serão lidos. O Lexis valida cada um, decide o
          encaminhamento e gera o relatório de exceções.
        </p>
      </CabecalhoPagina>

      <form onSubmit={aoEnviar} noValidate className="formulario">
        {passo === 0 ? (
          <fieldset className="cartao" ref={etapa} tabIndex={-1}>
            <legend>
              <span className="passo">1</span>Documentos
            </legend>
            <div className="envio">
              <label className="rotulo" htmlFor="arquivos">
                Arquivos PDF
              </label>
              <input
                id="arquivos"
                className="campo-arquivo"
                type="file"
                accept="application/pdf,.pdf"
                multiple
                aria-describedby={limites ? 'limites-envio' : undefined}
                onChange={(e) => {
                  adicionar(Array.from(e.target.files ?? []));
                  e.target.value = ''; // o campo vira só "adicionar": a lista abaixo é a fonte da verdade
                }}
              />
              {limites ? (
                <p className="nota" id="limites-envio">
                  Até {limites.max_arquivos} arquivos de {formatarBytes(limites.max_bytes_por_arquivo)} cada.
                  O servidor confere se o conteúdo é mesmo um PDF.
                </p>
              ) : null}
              {arquivos.length > 0 ? (
                <>
                  <div className="lista-selecao__barra">
                    <span className="nota" aria-live="polite">
                      {arquivos.length} arquivo(s) escolhido(s)
                    </span>
                    <button
                      type="button"
                      className="botao botao--texto botao--pequeno"
                      onClick={() => {
                        setArquivos([]);
                      }}
                    >
                      Limpar
                    </button>
                  </div>
                  <ul className="lista-selecao__itens lista-simples">
                    {arquivos.map((a) => (
                      <li key={a.name} className="opcao opcao--linha">
                        <Icone nome="arquivo" tamanho={16} className="opcao__icone" />
                        <span className="opcao__nome">{a.name}</span>
                        <span className="suave opcao__lado">({formatarBytes(a.size)})</span>
                        <button
                          type="button"
                          className="botao botao--texto botao--pequeno"
                          aria-label={`Remover ${a.name}`}
                          onClick={() => {
                            setArquivos((atuais) => atuais.filter((x) => x !== a));
                          }}
                        >
                          <Icone nome="limpar" tamanho={16} />
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </div>
          </fieldset>
        ) : (
          <fieldset className="cartao" ref={etapa} tabIndex={-1}>
            <legend>
              <span className="passo">2</span>Modo de leitura
            </legend>
            {saude.isPending ? <Carregando /> : null}
            {saude.isError ? <CaixaErro erro={saude.error} /> : null}
            <div className="opcoes-cartao">
              <label className="opcao-cartao">
                <input
                  type="radio"
                  name="modo"
                  value="replay"
                  checked={modo === 'replay'}
                  onChange={() => {
                    setModoEscolhido('replay');
                  }}
                />
                <Icone nome={ICONE_MODO.replay} tamanho={18} className="opcao-cartao__icone" />
                <span className="opcao-cartao__texto">
                  <strong>{ROTULO_MODO.replay}</strong>
                  <span className="opcao-cartao__selo">Sem chave de API</span>
                  <span className="nota">
                    Usa leituras já gravadas. Sem custo e sem enviar nada para fora. Documentos sem leitura
                    gravada terminam em falha.
                  </span>
                </span>
              </label>
              <label className={iaDisponivel ? 'opcao-cartao' : 'opcao-cartao opcao-cartao--desativada'}>
                <input
                  type="radio"
                  name="modo"
                  value="live"
                  checked={modo === 'live'}
                  disabled={!iaDisponivel}
                  onChange={() => {
                    setModoEscolhido('live');
                  }}
                />
                <Icone nome={ICONE_MODO.live} tamanho={18} className="opcao-cartao__icone" />
                <span className="opcao-cartao__texto">
                  <strong>{ROTULO_MODO.live}</strong>
                  <span className="opcao-cartao__selo">Com chave de API</span>
                  <span className="nota">
                    O modelo lê cada documento. Funciona com qualquer PDF e gera custo na sua conta da API.
                  </span>
                  {!iaDisponivel && infoIa?.motivo_indisponivel ? (
                    <span className="nota"> Indisponível: {infoIa.motivo_indisponivel}</span>
                  ) : null}
                </span>
              </label>
            </div>
            {saude.data ? (
              <p className="nota">
                Modelo em uso: <code>{saude.data.modelo}</code>. Informe a chave de API em{' '}
                <Link to="/configuracoes">Configurações</Link>.
              </p>
            ) : null}

            {saude.data?.ocr_disponivel ? (
              <details className="avancado">
                <summary>Opções avançadas</summary>
                <label className="opcao">
                  <input
                    type="checkbox"
                    checked={semOcr}
                    onChange={(e) => {
                      setSemOcr(e.target.checked);
                    }}
                  />
                  <span>
                    Não usar OCR local
                    <span className="nota">
                      {' '}
                      OCR é a leitura do texto de PDFs escaneados (imagem). Sem ele, esses PDFs sempre vão
                      para análise humana.
                    </span>
                  </span>
                </label>
              </details>
            ) : null}
          </fieldset>
        )}

        {erroLocal ? (
          <p role="alert" className="aviso aviso--erro">
            <Icone nome="erro" tamanho={18} className="aviso__icone" />
            <span>{erroLocal}</span>
          </p>
        ) : null}
        {iniciar.isError ? (
          <CaixaErro titulo="Não foi possível iniciar a execução" erro={iniciar.error} />
        ) : null}

        <div className="barra-acao">
          <p className="barra-acao__resumo">
            <strong>{arquivos.length}</strong> documento(s)
            {passo === 1 ? (
              <>
                {' '}
                · <strong>{ROTULO_MODO[modo]}</strong>
                {semOcr ? ' · sem OCR' : ''}
              </>
            ) : null}
          </p>
          <span className="linha">
            {passo === 1 ? (
              <button
                type="button"
                className="botao botao--secundario botao--grande"
                onClick={() => {
                  setPasso(0);
                }}
              >
                <Icone nome="esquerda" />
                Voltar
              </button>
            ) : null}
            {passo === 0 ? (
              <button type="submit" className="botao botao--grande">
                Continuar
                <Icone nome="direita" />
              </button>
            ) : (
              <button
                type="submit"
                className="botao botao--grande"
                disabled={iniciar.isPending || !saude.data}
              >
                <Icone nome="play" />
                {iniciar.isPending ? 'Iniciando…' : 'Executar'}
              </button>
            )}
          </span>
        </div>
      </form>

      <DialogoConfirmacao
        aberto={confirmando}
        titulo="A extração com IA gera custo"
        rotuloConfirmar="Entendi, executar com IA"
        perigo
        aoCancelar={() => {
          setConfirmando(false);
        }}
        aoConfirmar={() => {
          setConfirmando(false);
          enviar(true);
        }}
      >
        <p>
          Cada documento é enviado ao modelo <code>{saude.data?.modelo ?? '—'}</code>, com orçamento de até{' '}
          <strong>{saude.data?.orcamento_tokens.toLocaleString('pt-BR') ?? '—'} tokens</strong> por execução.
          O custo é cobrado na sua conta da API e só é estimado, não garantido.
        </p>
        <p>O texto dos PDFs sai desta máquina rumo ao provedor do modelo.</p>
      </DialogoConfirmacao>

      <ExecucoesRecentes />
    </>
  );
}
