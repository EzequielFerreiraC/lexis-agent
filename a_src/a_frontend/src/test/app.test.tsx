import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';
import type { Configuracao, ExecucaoItem, ExecucaoResumo, RevisaoHumana } from '../api/types';
import { App } from '../App';
import { restaurarPreferencias } from '../preferences/preferences';
import {
  CONFIGURACAO,
  REGISTRO_05,
  REGISTRO_07,
  SAUDE,
  corpoJson,
  json,
  paginaDeExecucoes,
  renderizarApp,
  simularApi,
  urlDe,
  violacoesDeAcessibilidade,
} from './util';

const ID = 'abcdef012345';

const execucao = (parcial: Partial<ExecucaoResumo> = {}): ExecucaoResumo => ({
  id: ID,
  criada_em: '2026-10-17T20:08:13+00:00',
  estado: 'CONCLUIDA',
  modo: 'replay',
  origem: 'amostras',
  total: 3,
  concluidos: 3,
  contagem: { APROVADO_AUTO: 1, REVISAO_HUMANA: 1, AGUARDA_EMISSOR: 1 },
  sem_ocr: false,
  extracoes_simuladas: true,
  versoes: {},
  documentos: [
    doc('01_ok.pdf', 'APROVADO_AUTO'),
    doc('05_datas.pdf', 'REVISAO_HUMANA', ['DATAS_PAGAMENTO_ANTES_DA_COM']),
    doc('04_pendente.pdf', 'AGUARDA_EMISSOR'),
  ],
  ...parcial,
});

function doc(
  arquivo: string,
  estado: 'APROVADO_AUTO' | 'REVISAO_HUMANA' | 'AGUARDA_EMISSOR',
  motivos: string[] = [],
) {
  return {
    arquivo,
    disposicao: 'PROCESSADO',
    estado,
    tipo: 'DIVIDENDO',
    fonte: 'NATIVO',
    golden: 'MATCH',
    confianca_minima: 'ALTA',
    motivos,
    tokens: 0,
    custo_estimado_usd: 0,
    tempo_ms: 120,
  };
}

const PNG = () =>
  new Response(new Uint8Array([137, 80, 78, 71]), { headers: { 'Content-Type': 'image/png' } });

describe('acesso', () => {
  it('sem token mostra só a tela de acesso e não chama a API', () => {
    const mock = simularApi({});
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole('heading', { name: /acesso ao console/i })).toBeInTheDocument();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(mock).not.toHaveBeenCalled();
  });

  it('o campo do token é do tipo senha e sem autocompletar', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const campo = screen.getByLabelText(/token de acesso/i);
    expect(campo).toHaveAttribute('type', 'password');
    expect(campo).toHaveAttribute('autocomplete', 'off');
  });
});

const PDF = (nome: string) => new File(['%PDF-1.7'], nome, { type: 'application/pdf' });
const ENVIO = { id: 'up0123456789', arquivos: [{ nome: '01_a.pdf', tamanho: 8, sha256: 'a'.repeat(64) }] };

/** Etapa 1: escolhe os PDFs e avança para a etapa do modo de leitura. */
async function escolherDocumentos(usuario: ReturnType<typeof userEvent.setup>, ...nomes: string[]) {
  await usuario.upload(await screen.findByLabelText(/arquivos pdf/i), nomes.map(PDF));
  await usuario.click(screen.getByRole('button', { name: 'Continuar' }));
  await screen.findByRole('group', { name: /modo de leitura/i });
}

const comIa = {
  ...SAUDE,
  modos: SAUDE.modos.map((m) =>
    m.id === 'live' ? { ...m, disponivel: true, motivo_indisponivel: null } : m,
  ),
};

describe('login (servidor com banco)', () => {
  const ANA = { login: 'ana@lexis.dev', nome: 'Ana Lima' };

  it('pede login antes de qualquer tela e, ao entrar, mostra o usuário e esquece a senha', async () => {
    const usuario = userEvent.setup();
    let logado = false;
    const mock = simularApi({
      'GET /api/sessao': () =>
        json({ login_exigido: true, usuario: logado ? ANA : null, dominios_email: [] }),
      'POST /api/sessao': () => {
        logado = true;
        return json({ login_exigido: true, usuario: ANA, dominios_email: [] });
      },
    });
    const { container } = renderizarApp();
    expect(await screen.findByRole('heading', { name: 'Entrar' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Principal' })).not.toBeInTheDocument();
    expect(await violacoesDeAcessibilidade(container)).toEqual([]);

    await usuario.type(screen.getByLabelText('E-mail'), 'ana@lexis.dev');
    await usuario.type(screen.getByLabelText('Senha'), 'senha-do-operador-longa');
    await usuario.click(screen.getByRole('button', { name: 'Entrar' }));

    expect(await screen.findByText('Ana Lima')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Principal' })).toBeInTheDocument();
    const chamada = mock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(corpoJson(chamada?.[1])).toEqual({ login: 'ana@lexis.dev', senha: 'senha-do-operador-longa' });
    expect(document.body.textContent).not.toContain('senha-do-operador-longa');
  });

  it('senha errada mostra o motivo e limpa a senha', async () => {
    const usuario = userEvent.setup();
    simularApi({
      'GET /api/sessao': () => json({ login_exigido: true, usuario: null, dominios_email: [] }),
      'POST /api/sessao': () => json({ detail: 'e-mail ou senha inválidos' }, 401),
    });
    renderizarApp();
    await usuario.type(await screen.findByLabelText('E-mail'), 'ana@lexis.dev');
    await usuario.type(screen.getByLabelText('Senha'), 'errada-mas-longa');
    await usuario.click(screen.getByRole('button', { name: 'Entrar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('e-mail ou senha inválidos');
    expect(screen.getByLabelText('Senha')).toHaveValue('');
  });

  it('sair encerra a sessão no servidor e volta para o login', async () => {
    const usuario = userEvent.setup();
    let logado = true;
    const mock = simularApi({
      'GET /api/sessao': () =>
        json({ login_exigido: true, usuario: logado ? ANA : null, dominios_email: [] }),
      'DELETE /api/sessao': () => {
        logado = false;
        return json({ login_exigido: true, usuario: null, dominios_email: [] });
      },
    });
    renderizarApp();
    await screen.findByText('Ana Lima');
    await usuario.click(screen.getByRole('button', { name: 'Sair' }));
    expect(await screen.findByRole('heading', { name: 'Entrar' })).toBeInTheDocument();
    expect(mock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(true);
  });
  it('cria a conta pela tela de login e já entra com ela', async () => {
    const usuario = userEvent.setup();
    let logado = false;
    const BRUNO = { login: 'bruno@lexis.dev', nome: 'Bruno Reis' };
    const mock = simularApi({
      'GET /api/sessao': () =>
        json({ login_exigido: true, usuario: logado ? BRUNO : null, dominios_email: [] }),
      'POST /api/usuarios': () => {
        logado = true;
        return json({ login_exigido: true, usuario: BRUNO, dominios_email: [] }, 201);
      },
    });
    const { container } = renderizarApp();
    await usuario.click(await screen.findByRole('button', { name: 'Criar conta' }));
    expect(screen.getByRole('heading', { name: 'Criar conta' })).toBeInTheDocument();
    expect(await violacoesDeAcessibilidade(container)).toEqual([]);

    await usuario.type(screen.getByLabelText('Apelido'), 'Bruno Reis');
    await usuario.type(screen.getByLabelText('E-mail'), 'bruno@lexis.dev');
    await usuario.type(screen.getByLabelText('Senha'), 'senha-nova-bem-longa');
    await usuario.type(screen.getByLabelText('Confirmar senha'), 'senha-nova-diferente');
    expect(screen.getByText('As senhas não conferem.')).toBeInTheDocument();
    const criar = screen.getByRole('button', { name: 'Criar conta' });
    expect(criar).toBeDisabled();

    await usuario.clear(screen.getByLabelText('Confirmar senha'));
    await usuario.type(screen.getByLabelText('Confirmar senha'), 'senha-nova-bem-longa');
    await usuario.click(criar);

    expect(await screen.findByText('Bruno Reis')).toBeInTheDocument();
    const chamada = mock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(corpoJson(chamada?.[1])).toEqual({
      nome: 'Bruno Reis',
      login: 'bruno@lexis.dev',
      senha: 'senha-nova-bem-longa',
    });
    expect(document.body.textContent).not.toContain('senha-nova-bem-longa');
  });

  it('com domínios configurados, avisa o e-mail de fora antes de enviar', async () => {
    const usuario = userEvent.setup();
    simularApi({
      'GET /api/sessao': () => json({ login_exigido: true, usuario: null, dominios_email: ['lexis.dev'] }),
    });
    renderizarApp();
    await usuario.click(await screen.findByRole('button', { name: 'Criar conta' }));
    expect(screen.getByText('Usado para entrar. Use seu e-mail @lexis.dev.')).toBeInTheDocument();
    await usuario.type(screen.getByLabelText('Apelido'), 'Bruno');
    await usuario.type(screen.getByLabelText('E-mail'), 'bruno@gmail.com');
    await usuario.type(screen.getByLabelText('Senha'), 'senha-nova-bem-longa');
    await usuario.type(screen.getByLabelText('Confirmar senha'), 'senha-nova-bem-longa');
    expect(screen.getByText('Use um e-mail @lexis.dev.')).toBeInTheDocument();
    expect(screen.getByLabelText('E-mail')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('button', { name: 'Criar conta' })).toBeDisabled();
  });

  it('login em uso mostra o motivo e volta para entrar sem perder a tela', async () => {
    const usuario = userEvent.setup();
    simularApi({
      'GET /api/sessao': () => json({ login_exigido: true, usuario: null, dominios_email: [] }),
      'POST /api/usuarios': () => json({ detail: 'esse e-mail já tem uma conta' }, 409),
    });
    renderizarApp();
    await usuario.click(await screen.findByRole('button', { name: 'Criar conta' }));
    await usuario.type(screen.getByLabelText('Apelido'), 'Ana Lima');
    await usuario.type(screen.getByLabelText('E-mail'), 'ana@lexis.dev');
    await usuario.type(screen.getByLabelText('Senha'), 'senha-nova-bem-longa');
    await usuario.type(screen.getByLabelText('Confirmar senha'), 'senha-nova-bem-longa');
    await usuario.click(screen.getByRole('button', { name: 'Criar conta' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('esse e-mail já tem uma conta');
    await usuario.click(screen.getByRole('button', { name: 'Entrar' }));
    expect(screen.getByRole('heading', { name: 'Entrar' })).toBeInTheDocument();
  });
});

describe('Executar', () => {
  it('não oferece amostras: a única origem é o envio de PDFs', async () => {
    simularApi({});
    renderizarApp();
    await screen.findByRole('heading', { name: /nova execução/i });
    expect(screen.queryByText(/amostras/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/arquivos pdf/i)).toBeInTheDocument();
  });

  it('mostra o passo a passo e marca a etapa atual', async () => {
    const usuario = userEvent.setup();
    simularApi({});
    renderizarApp();
    const etapas = await screen.findByRole('navigation', { name: 'Etapas' });
    expect(within(etapas).getAllByRole('listitem')).toHaveLength(4);
    expect(within(etapas).getByText('Documentos').closest('li')).toHaveAttribute('aria-current', 'step');

    await escolherDocumentos(usuario, '01_a.pdf');
    expect(within(etapas).getByText('Modo de leitura').closest('li')).toHaveAttribute('aria-current', 'step');
    await usuario.click(within(etapas).getByRole('button', { name: /documentos/i }));
    expect(await screen.findByLabelText(/arquivos pdf/i)).toBeInTheDocument();
    expect(screen.getByText('01_a.pdf')).toBeInTheDocument(); // voltar não perde a escolha
  });

  it('não avança sem documentos', async () => {
    const usuario = userEvent.setup();
    const mock = simularApi({});
    renderizarApp();
    await usuario.click(await screen.findByRole('button', { name: 'Continuar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/ao menos um arquivo PDF/);
    expect(mock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
  });

  it('envia os PDFs e inicia uma demonstração (sem chave), abrindo a execução', async () => {
    const usuario = userEvent.setup();
    const mock = simularApi({
      'POST /api/uploads': () => json(ENVIO),
      'POST /api/execucoes': () => json(execucao({ estado: 'EM_ANDAMENTO', concluidos: 0, documentos: [] })),
      [`GET /api/execucoes/${ID}`]: () => json(execucao()),
    });
    renderizarApp();
    await escolherDocumentos(usuario, '01_a.pdf');
    expect(screen.getByRole('radio', { name: /demonstração/i })).toBeChecked();
    await usuario.click(screen.getByRole('button', { name: 'Executar' }));

    await screen.findByRole('heading', { name: `Execução ${ID}` });
    const chamada = mock.mock.calls.find(
      ([entrada, init]) => init?.method === 'POST' && urlDe(entrada).endsWith('/api/execucoes'),
    );
    expect(corpoJson(chamada?.[1])).toMatchObject({
      origem: 'upload',
      upload_id: ENVIO.id,
      modo: 'replay',
      confirmar_live: false,
    });
  });

  it('oferece só dois modos e desativa a extração com IA sem chave, explicando o motivo', async () => {
    const usuario = userEvent.setup();
    simularApi({});
    renderizarApp();
    await escolherDocumentos(usuario, '01_a.pdf');
    expect(screen.getAllByRole('radio')).toHaveLength(2);
    expect(screen.getByRole('radio', { name: /extração com ia/i })).toBeDisabled();
    expect(screen.getByText(/ANTHROPIC_API_KEY ausente/)).toBeInTheDocument();
  });

  it('com chave, começa na extração com IA', async () => {
    const usuario = userEvent.setup();
    simularApi({ 'GET /api/saude': () => json(comIa) });
    renderizarApp();
    await escolherDocumentos(usuario, '01_a.pdf');
    expect(screen.getByRole('radio', { name: /extração com ia/i })).toBeChecked();
  });

  it('remove um arquivo da lista antes de continuar', async () => {
    const usuario = userEvent.setup();
    simularApi({});
    renderizarApp();
    await usuario.upload(await screen.findByLabelText(/arquivos pdf/i), [PDF('01_a.pdf'), PDF('02_b.pdf')]);
    await usuario.click(screen.getByRole('button', { name: 'Remover 02_b.pdf' }));
    expect(screen.queryByText('02_b.pdf')).not.toBeInTheDocument();
    expect(screen.getByText(/1 arquivo\(s\) escolhido/)).toBeInTheDocument();
  });

  it('exige confirmação explícita antes da extração com IA (gera custo)', async () => {
    const usuario = userEvent.setup();
    const mock = simularApi({
      'GET /api/saude': () => json(comIa),
      'POST /api/uploads': () => json(ENVIO),
      'POST /api/execucoes': () => json(execucao({ modo: 'live', extracoes_simuladas: false })),
      [`GET /api/execucoes/${ID}`]: () => json(execucao({ modo: 'live', extracoes_simuladas: false })),
    });
    renderizarApp();
    await escolherDocumentos(usuario, '01_a.pdf');
    await usuario.click(screen.getByRole('button', { name: 'Executar' }));

    const dialogo = await screen.findByRole('dialog');
    expect(within(dialogo).getByText(/400\.000 tokens/)).toBeInTheDocument();
    expect(mock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);

    await usuario.click(within(dialogo).getByRole('button', { name: 'Cancelar' }));
    expect(mock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);

    await usuario.click(screen.getByRole('button', { name: 'Executar' }));
    await usuario.click(await screen.findByRole('button', { name: /entendi, executar com ia/i }));
    await screen.findByRole('heading', { name: `Execução ${ID}` });
    const chamada = mock.mock.calls.find(
      ([entrada, init]) => init?.method === 'POST' && urlDe(entrada).endsWith('/api/execucoes'),
    );
    expect(corpoJson(chamada?.[1])).toMatchObject({ modo: 'live', confirmar_live: true });
  });

  it('OCR fica recolhido em opções avançadas e só aparece quando o servidor tem OCR', async () => {
    const usuario = userEvent.setup();
    simularApi({ 'GET /api/saude': () => json({ ...SAUDE, ocr_disponivel: true }) });
    renderizarApp();
    await escolherDocumentos(usuario, '01_a.pdf');
    const ocr = screen.getByRole('checkbox', { name: /não usar ocr local/i });
    expect(ocr).not.toBeVisible();
    await usuario.click(screen.getByText('Opções avançadas'));
    expect(ocr).toBeVisible();
    expect(ocr).not.toBeChecked();
    expect(screen.getByText(/Sem ele, esses PDFs sempre vão para análise humana/)).toBeInTheDocument();
  });

  it('sem OCR no servidor, não mostra a opção', async () => {
    const usuario = userEvent.setup();
    simularApi({});
    renderizarApp();
    await escolherDocumentos(usuario, '01_a.pdf');
    expect(screen.queryByText('Opções avançadas')).not.toBeInTheDocument();
  });

  it('recusa no navegador arquivo que não é PDF, sem chamar a API', async () => {
    const usuario = userEvent.setup({ applyAccept: false });
    const mock = simularApi({});
    renderizarApp();
    await usuario.upload(await screen.findByLabelText(/arquivos pdf/i), new File(['x'], 'planilha.xlsx'));
    await usuario.click(screen.getByRole('button', { name: 'Continuar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/não é um PDF/);
    expect(mock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
  });

  it('mostra o erro do servidor ao iniciar', async () => {
    const usuario = userEvent.setup();
    simularApi({
      'POST /api/uploads': () => json(ENVIO),
      'POST /api/execucoes': () => json({ detail: 'documento desconhecido' }, 400),
    });
    renderizarApp();
    await escolherDocumentos(usuario, '01_a.pdf');
    await usuario.click(screen.getByRole('button', { name: 'Executar' }));
    expect(await screen.findByText(/documento desconhecido/)).toBeInTheDocument();
  });

  it('não tem violações de acessibilidade', async () => {
    const usuario = userEvent.setup();
    simularApi({});
    const { container } = renderizarApp();
    await usuario.upload(await screen.findByLabelText(/arquivos pdf/i), [PDF('01_a.pdf')]);
    expect(await violacoesDeAcessibilidade(container)).toEqual([]);
    await usuario.click(screen.getByRole('button', { name: 'Continuar' }));
    await screen.findByRole('group', { name: /modo de leitura/i });
    expect(await violacoesDeAcessibilidade(container)).toEqual([]);
  });
});

describe('Execução', () => {
  it('acompanha o progresso até concluir (polling)', async () => {
    let consultas = 0;
    simularApi({
      [`GET /api/execucoes/${ID}`]: () => {
        consultas += 1;
        return json(
          consultas === 1 ? execucao({ estado: 'EM_ANDAMENTO', concluidos: 1, documentos: [] }) : execucao(),
        );
      },
    });
    renderizarApp(`/execucoes/${ID}`);
    const progresso = await screen.findByRole('progressbar');
    expect(progresso).toHaveAttribute('value', '1');
    expect(progresso).toHaveAttribute('max', '3');
    await screen.findByRole('table', {}, { timeout: 4000 });
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('avisa que as extrações são simuladas e lista o que exige atuação primeiro', async () => {
    simularApi({ [`GET /api/execucoes/${ID}`]: () => json(execucao()) });
    renderizarApp(`/execucoes/${ID}`);
    expect(await screen.findByText(/extrações simuladas/i)).toBeInTheDocument();
    const linhas = within(await screen.findByRole('table'))
      .getAllByRole('row')
      .slice(1);
    expect(linhas[0]).toHaveTextContent('05_datas.pdf');
    expect(linhas[0]).toHaveTextContent('DATAS_PAGAMENTO_ANTES_DA_COM');
    expect(linhas.at(-1)).toHaveTextContent('01_ok.pdf');
  });

  it('filtra por decisão', async () => {
    const usuario = userEvent.setup();
    simularApi({ [`GET /api/execucoes/${ID}`]: () => json(execucao()) });
    renderizarApp(`/execucoes/${ID}`);
    await usuario.selectOptions(await screen.findByLabelText(/filtrar por decisão/i), 'APROVADO_AUTO');
    const linhas = within(screen.getByRole('table')).getAllByRole('row').slice(1);
    expect(linhas).toHaveLength(1);
    expect(linhas[0]).toHaveTextContent('01_ok.pdf');
  });

  it('mostra a falha da execução', async () => {
    simularApi({
      [`GET /api/execucoes/${ID}`]: () =>
        json(execucao({ estado: 'FALHOU', erro: 'interrompida', documentos: [] })),
    });
    renderizarApp(`/execucoes/${ID}`);
    expect(await screen.findByText('interrompida')).toBeInTheDocument();
  });

  it('baixa o relatório pela API com autorização', async () => {
    const usuario = userEvent.setup();
    const mock = simularApi({
      [`GET /api/execucoes/${ID}`]: () => json(execucao()),
      [`GET /api/execucoes/${ID}/relatorios/relatorio_excecoes.md`]: () => new Response('# relatório'),
    });
    renderizarApp(`/execucoes/${ID}`);
    await usuario.click(await screen.findByRole('button', { name: /relatório de exceções \(legível\)/i }));
    await waitFor(() => {
      expect(mock.mock.calls.some(([url]) => urlDe(url).endsWith('/relatorios/relatorio_excecoes.md'))).toBe(
        true,
      );
    });
  });

  it('execução inexistente mostra erro claro', async () => {
    simularApi({});
    renderizarApp('/execucoes/000000000000');
    expect(await screen.findByText(/execução não encontrada/i)).toBeInTheDocument();
  });

  it('não tem violações de acessibilidade', async () => {
    simularApi({ [`GET /api/execucoes/${ID}`]: () => json(execucao()) });
    const { container } = renderizarApp(`/execucoes/${ID}`);
    await screen.findByRole('table');
    expect(await violacoesDeAcessibilidade(container)).toEqual([]);
  });
});

describe('Documento', () => {
  const rota = (arquivo: string) => `/execucoes/${ID}/documentos/${encodeURIComponent(arquivo)}`;
  const base = (arquivo: string, registro: unknown, paginas = 1) => ({
    [`GET /api/execucoes/${ID}`]: () => json(execucao({ documentos: [doc(arquivo, 'REVISAO_HUMANA')] })),
    [`GET /api/execucoes/${ID}/documentos/${arquivo}`]: () => json(registro),
    [`GET /api/execucoes/${ID}/documentos/${arquivo}/paginas/1`]: () =>
      json({ numero: 1, total_paginas: paginas, largura_pt: 600, altura_pt: 800 }),
    [`GET /api/execucoes/${ID}/documentos/${arquivo}/paginas/1/imagem`]: PNG,
  });

  it('mostra a decisão, o motivo e os campos agrupados', async () => {
    simularApi(base('05.pdf', REGISTRO_05));
    renderizarApp(rota('05.pdf'));
    expect(await screen.findByRole('heading', { level: 2, name: /revisão humana/i })).toBeInTheDocument();
    expect(screen.getByText(/linha da tabela de decisão: L2/i)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Datas' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Data de pagamento.*10\/07\/2026/ })).toBeInTheDocument();
  });

  it('diz o que falta para aprovar: nenhum bloqueio basta sozinho, juntos aprovam', async () => {
    simularApi(base('05.pdf', REGISTRO_05));
    renderizarApp(rota('05.pdf'));
    const bloco = (await screen.findByRole('heading', { name: /o que falta para aprovar/i })).parentElement;
    if (!bloco) throw new Error('bloco ausente');
    expect(within(bloco).getAllByText(/sozinho não basta/i)).toHaveLength(2);
    expect(within(bloco).getByText(/só com tudo resolvido junto/i)).toBeInTheDocument();
    expect(within(bloco).getByText('Aprovado automaticamente')).toBeInTheDocument();
  });

  it('documento aprovado não mostra o que falta para aprovar', async () => {
    simularApi(base('07.pdf', REGISTRO_07));
    renderizarApp(rota('07.pdf'));
    await screen.findByRole('tab', { name: /campos/i });
    expect(screen.queryByRole('heading', { name: /o que falta para aprovar/i })).not.toBeInTheDocument();
  });

  it('ao escolher um campo, mostra o trecho literal e destaca a posição na página', async () => {
    const usuario = userEvent.setup();
    simularApi(base('05.pdf', REGISTRO_05));
    renderizarApp(rota('05.pdf'));
    const botao = await screen.findByRole('button', { name: /Data de pagamento/ });
    expect(botao).toHaveAttribute('aria-expanded', 'false');
    await usuario.click(botao);
    expect(botao).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(/“10\/07\/2026”/)).toBeInTheDocument();
    const caixa = await screen.findByTestId('destaque-bbox');
    expect(caixa.style.left).toBe(`${((238.4 / 600) * 100).toFixed(3)}%`);
    expect(caixa.style.top).toBe(`${((381.1 / 800) * 100).toFixed(3)}%`);
  });

  it('em documento escaneado diz que não há posição, em vez de inventar um destaque', async () => {
    const usuario = userEvent.setup();
    simularApi(base('07.pdf', REGISTRO_07));
    renderizarApp(rota('07.pdf'));
    await usuario.click(await screen.findByRole('button', { name: /Data de pagamento/ }));
    expect(await screen.findByText(/sem posição na página/i, { selector: 'p' })).toBeInTheDocument();
    expect(screen.queryByTestId('destaque-bbox')).not.toBeInTheDocument();
  });

  it('a aba Conferência leva o operador ao trecho na página', async () => {
    const usuario = userEvent.setup();
    simularApi(base('05.pdf', REGISTRO_05));
    renderizarApp(rota('05.pdf'));
    await usuario.click(await screen.findByRole('tab', { name: /conferência/i }));
    expect(screen.getByText(/data_pagamento >= data_com/)).toBeInTheDocument();
    await usuario.click(screen.getAllByRole('button', { name: /ver na página/i })[0] as HTMLElement);
    expect(await screen.findByTestId('destaque-bbox')).toBeInTheDocument();
  });

  it('a aba Validação mostra a base de referência e filtra as regras que falharam', async () => {
    const usuario = userEvent.setup();
    simularApi(base('05.pdf', REGISTRO_05));
    renderizarApp(rota('05.pdf'));
    await usuario.click(await screen.findByRole('tab', { name: /validação/i }));
    expect(screen.getByText(/confirmado na base/i)).toBeInTheDocument();
    const antes = screen.getAllByRole('listitem').length;
    await usuario.click(screen.getByRole('checkbox', { name: /mostrar só o que não passou/i }));
    expect(screen.getAllByRole('listitem').length).toBeLessThan(antes);
    expect(screen.getAllByText('DATAS_PAGAMENTO_ANTES_DA_COM').length).toBeGreaterThan(0);
  });

  it('a aba Auditoria mostra sha256, versões e chamadas', async () => {
    const usuario = userEvent.setup();
    simularApi(base('05.pdf', REGISTRO_05));
    renderizarApp(rota('05.pdf'));
    await usuario.click(await screen.findByRole('tab', { name: /auditoria/i }));
    expect(
      screen.getByText(/925b6eb09fbcaecf81d3c1d125e041edd1460fed23d6a67bf10f8a6b170e9567/),
    ).toBeInTheDocument();
    expect(screen.getByText('consultar_golden')).toBeInTheDocument();
  });

  it('não interpreta HTML vindo do documento (texto literal é só texto)', async () => {
    const usuario = userEvent.setup();
    const malicioso = structuredClone(REGISTRO_05);
    const campoData = malicioso.campos.data_pagamento;
    if (!campoData) throw new Error('fixture sem data_pagamento');
    campoData.texto_literal = '<img src=x onerror=alert(1)><script>alert(2)</script>';
    simularApi(base('05.pdf', malicioso));
    const { container } = renderizarApp(rota('05.pdf'));
    await usuario.click(await screen.findByRole('button', { name: /Data de pagamento/ }));
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img[src="x"]')).toBeNull();
    expect(screen.getByText(/<script>alert\(2\)<\/script>/)).toBeInTheDocument();
  });

  it('não tem violações de acessibilidade em nenhuma aba', async () => {
    const usuario = userEvent.setup();
    simularApi(base('05.pdf', REGISTRO_05));
    const { container } = renderizarApp(rota('05.pdf'));
    await screen.findByRole('tab', { name: /campos/i });
    expect(await violacoesDeAcessibilidade(container)).toEqual([]);
    for (const nome of [/validação/i, /conferência/i, /auditoria/i]) {
      await usuario.click(screen.getByRole('tab', { name: nome }));
      expect(await violacoesDeAcessibilidade(container)).toEqual([]);
    }
  });

  it('documento inexistente mostra erro claro', async () => {
    simularApi({});
    renderizarApp(rota('x.pdf'));
    expect(await screen.findByText(/documento não encontrado/i)).toBeInTheDocument();
  });
});

describe('Revisão humana', () => {
  const NOME = '05.pdf';
  const rota = `/execucoes/${ID}/documentos/${NOME}`;
  const MOTIVOS = ['DATAS_PAGAMENTO_ANTES_DA_COM', 'DATAS_PAGAMENTO_ANTES_DA_EX'];
  const REVISAO: RevisaoHumana = {
    decisao: 'APROVADO_NA_REVISAO',
    operador: 'Operadora A',
    justificativa: 'Conferido contra o aviso original.',
    motivos_reconhecidos: MOTIVOS,
    decisao_automatica: 'REVISAO_HUMANA',
    sha256_registro: 'c'.repeat(64),
    revisada_em: '2026-10-20T21:00:00+00:00',
  };
  const comRevisao = (revisao: RevisaoHumana | null) =>
    execucao({ documentos: [{ ...doc(NOME, 'REVISAO_HUMANA', MOTIVOS), revisao }] });

  function rotas(revisaoAtual: { valor: RevisaoHumana | null }, registro: unknown = REGISTRO_05) {
    return {
      [`GET /api/execucoes/${ID}`]: () => json(comRevisao(revisaoAtual.valor)),
      [`GET /api/execucoes/${ID}/documentos/${NOME}`]: () => json(registro),
      [`GET /api/execucoes/${ID}/documentos/${NOME}/paginas/1`]: () =>
        json({ numero: 1, total_paginas: 1, largura_pt: 600, altura_pt: 800 }),
      [`GET /api/execucoes/${ID}/documentos/${NOME}/paginas/1/imagem`]: PNG,
    };
  }

  async function preencher(usuario: ReturnType<typeof userEvent.setup>, decisao: RegExp) {
    await usuario.click(await screen.findByRole('radio', { name: decisao }));
    await usuario.type(screen.getByLabelText(/quem está revisando/i), 'Operadora A');
    await usuario.type(screen.getByLabelText(/justificativa/i), 'Conferido contra o aviso original.');
  }

  it('aprovar exige marcar todos os motivos, pede confirmação e mostra a decisão registrada', async () => {
    const usuario = userEvent.setup();
    const atual = { valor: null as RevisaoHumana | null };
    const mock = simularApi({
      ...rotas(atual),
      [`POST /api/execucoes/${ID}/documentos/${NOME}/revisao`]: () => {
        atual.valor = REVISAO;
        return json(REVISAO, 201);
      },
    });
    renderizarApp(rota);
    await preencher(usuario, /aprovado na revisão/i);
    const registrar = screen.getByRole('button', { name: /registrar decisão/i });
    expect(registrar).toBeDisabled();
    expect(screen.getByText(/marque todos os motivos como conferidos/i)).toBeInTheDocument();

    await usuario.click(screen.getByRole('checkbox', { name: /DATAS_PAGAMENTO_ANTES_DA_COM/ }));
    expect(registrar).toBeDisabled();
    await usuario.click(screen.getByRole('checkbox', { name: /DATAS_PAGAMENTO_ANTES_DA_EX/ }));
    expect(registrar).toBeEnabled();

    await usuario.click(registrar);
    const dialogo = await screen.findByRole('dialog');
    expect(within(dialogo).getByText(/não pode ser desfeita/i)).toBeInTheDocument();
    expect(mock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
    await usuario.click(within(dialogo).getByRole('button', { name: 'Registrar' }));

    expect(
      await screen.findByText('Conferido contra o aviso original.', { selector: 'dd' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /registrar decisão/i })).not.toBeInTheDocument();
    const chamada = mock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(corpoJson(chamada?.[1])).toEqual({
      decisao: 'APROVADO_NA_REVISAO',
      operador: 'Operadora A',
      justificativa: 'Conferido contra o aviso original.',
      motivos_reconhecidos: MOTIVOS,
    });
  });

  it('com login, quem revisa é o usuário da sessão e o nome não é digitado', async () => {
    const usuario = userEvent.setup();
    const atual = { valor: null as RevisaoHumana | null };
    const mock = simularApi({
      ...rotas(atual),
      'GET /api/sessao': () =>
        json({ login_exigido: true, usuario: { login: 'ana', nome: 'Ana Lima' }, dominios_email: [] }),
      [`POST /api/execucoes/${ID}/documentos/${NOME}/revisao`]: () => {
        atual.valor = { ...REVISAO, decisao: 'REJEITADO_NA_REVISAO', operador: 'Ana Lima', usuario: 'ana' };
        return json(atual.valor, 201);
      },
    });
    renderizarApp(rota);
    await usuario.click(await screen.findByRole('radio', { name: /rejeitado na revisão/i }));
    expect(screen.getByText(/revisando como/i)).toHaveTextContent('Revisando como Ana Lima (ana)');
    expect(screen.queryByLabelText(/quem está revisando/i)).not.toBeInTheDocument();
    await usuario.type(screen.getByLabelText(/justificativa/i), 'Pagamento antes da data com.');
    await usuario.click(screen.getByRole('button', { name: /registrar decisão/i }));
    await usuario.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Registrar' }));
    await waitFor(() => {
      expect(mock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true);
    });
    const chamada = mock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(corpoJson(chamada?.[1])).toMatchObject({ decisao: 'REJEITADO_NA_REVISAO', operador: null });
  });

  it('rejeitar não exige motivos e mostra a recusa do servidor', async () => {
    const usuario = userEvent.setup();
    simularApi({
      ...rotas({ valor: null }),
      [`POST /api/execucoes/${ID}/documentos/${NOME}/revisao`]: () =>
        json({ detail: 'este documento já foi revisado nesta execução' }, 409),
    });
    renderizarApp(rota);
    await preencher(usuario, /rejeitado na revisão/i);
    await usuario.click(screen.getByRole('button', { name: /registrar decisão/i }));
    await usuario.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Registrar' }));
    expect(await screen.findByText(/já foi revisado nesta execução/i)).toBeInTheDocument();
  });

  it('decisão já registrada aparece no documento e na lista, sem formulário', async () => {
    simularApi(rotas({ valor: REVISAO }));
    renderizarApp(rota);
    expect(await screen.findByText('Operadora A', { selector: 'dd' })).toBeInTheDocument();
    expect(screen.getAllByText(/aprovado na revisão/i, { selector: 'span' }).length).toBeGreaterThan(0);
    expect(screen.queryByRole('radio', { name: /aprovado na revisão/i })).not.toBeInTheDocument();
  });

  it('a lista de documentos mostra a decisão humana ao lado da automática', async () => {
    simularApi({ [`GET /api/execucoes/${ID}`]: () => json(comRevisao(REVISAO)) });
    renderizarApp(`/execucoes/${ID}`);
    const linha = (await screen.findByRole('link', { name: new RegExp(NOME) })).closest('tr');
    expect(within(linha as HTMLElement).getByText(/aprovado na revisão/i)).toBeInTheDocument();
    expect(within(linha as HTMLElement).getByText(/revisão humana/i)).toBeInTheDocument();
  });

  it('documento aprovado automaticamente não oferece decisão do operador', async () => {
    simularApi(rotas({ valor: null }, REGISTRO_07));
    renderizarApp(rota);
    await screen.findByRole('tab', { name: /campos/i });
    expect(screen.queryByRole('heading', { name: /decisão do operador/i })).not.toBeInTheDocument();
  });

  it('não tem violações de acessibilidade no formulário nem na decisão registrada', async () => {
    simularApi(rotas({ valor: null }));
    const { container, unmount } = renderizarApp(rota);
    await screen.findByRole('heading', { name: /decisão do operador/i });
    expect(await violacoesDeAcessibilidade(container)).toEqual([]);
    unmount();
    simularApi(rotas({ valor: REVISAO }));
    const outra = renderizarApp(rota);
    await screen.findByText('Operadora A', { selector: 'dd' });
    expect(await violacoesDeAcessibilidade(outra.container)).toEqual([]);
  });
});

const item = (n: number): ExecucaoItem => ({
  id: n.toString(16).padStart(12, '0'),
  criada_em: `2026-10-${String(n).padStart(2, '0')}T10:00:00+00:00`,
  estado: 'CONCLUIDA',
  modo: 'replay',
  origem: 'upload',
  total: 1,
  concluidos: 1,
  contagem: { APROVADO_AUTO: 1 },
});
/** 45 execuções, da mais nova (dia 45 "virtual") para a mais antiga. */
const MUITAS = Array.from({ length: 45 }, (_, i) => item(45 - i));

describe('Histórico', () => {
  it('fica no menu no lugar da avaliação e pagina 20 por vez', async () => {
    const usuario = userEvent.setup();
    const mock = simularApi({ 'GET /api/execucoes': (url) => json(paginaDeExecucoes(MUITAS, url)) });
    renderizarApp();
    expect(screen.queryByRole('link', { name: 'Avaliação' })).not.toBeInTheDocument();
    await usuario.click(await screen.findByRole('link', { name: 'Histórico' }));
    await screen.findByRole('heading', { name: 'Histórico', level: 1 });

    const paginacao = await screen.findByRole('navigation', { name: 'Paginação' });
    expect(paginacao).toHaveTextContent('Mostrando 1–20 de 45');
    expect(within(paginacao).getByText('Página 1 de 3')).toBeInTheDocument();
    expect(within(paginacao).getByRole('button', { name: /anterior/i })).toBeDisabled();
    expect(screen.getAllByRole('link', { name: /documento\(s\)/ })).toHaveLength(20);

    await usuario.click(within(paginacao).getByRole('button', { name: /próxima/i }));
    await waitFor(() => {
      expect(paginacao).toHaveTextContent('Mostrando 21–40 de 45');
    });
    await usuario.click(within(paginacao).getByRole('button', { name: /próxima/i }));
    await waitFor(() => {
      expect(paginacao).toHaveTextContent('Mostrando 41–45 de 45');
    });
    expect(within(paginacao).getByRole('button', { name: /próxima/i })).toBeDisabled();
    expect(screen.getAllByRole('link', { name: /documento\(s\)/ })).toHaveLength(5);

    const pedidos = mock.mock.calls
      .map(([entrada]) => new URL(urlDe(entrada), 'http://x'))
      .filter((u) => u.pathname === '/api/execucoes' && u.searchParams.get('limite') === '20')
      .map((u) => u.searchParams.get('deslocamento'));
    expect(pedidos).toEqual(expect.arrayContaining(['0', '20', '40'])); // a paginação é no servidor
  });

  it('abre direto na página da URL', async () => {
    simularApi({ 'GET /api/execucoes': (url) => json(paginaDeExecucoes(MUITAS, url)) });
    renderizarApp('/historico?pagina=3');
    expect(await screen.findByText('Página 3 de 3')).toBeInTheDocument();
  });

  it('página além do fim oferece voltar ao início', async () => {
    const usuario = userEvent.setup();
    simularApi({ 'GET /api/execucoes': (url) => json(paginaDeExecucoes(MUITAS, url)) });
    renderizarApp('/historico?pagina=99');
    await usuario.click(await screen.findByRole('button', { name: /voltar para a primeira página/i }));
    expect(await screen.findByText('Página 1 de 3')).toBeInTheDocument();
  });

  it('sem execuções, não mostra paginação e leva a executar', async () => {
    simularApi({});
    renderizarApp('/historico');
    expect(await screen.findByText('Nenhuma execução ainda')).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Paginação' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /envie os primeiros documentos/i })).toHaveAttribute('href', '/');
  });

  it('em Executar, mostra só as 5 recentes e leva ao histórico completo', async () => {
    simularApi({ 'GET /api/execucoes': (url) => json(paginaDeExecucoes(MUITAS, url)) });
    renderizarApp();
    const recentes = await screen.findByRole('region', { name: 'Execuções recentes' });
    await waitFor(() => {
      expect(within(recentes).getAllByRole('link', { name: /documento\(s\)/ })).toHaveLength(5);
    });
    expect(within(recentes).getByRole('link', { name: /ver todas \(45\)/i })).toHaveAttribute(
      'href',
      '/historico',
    );
  });

  it('a trilha da execução volta para o histórico', async () => {
    simularApi({ [`GET /api/execucoes/${ID}`]: () => json(execucao()) });
    renderizarApp(`/execucoes/${ID}`);
    const trilha = await screen.findByRole('navigation', { name: 'Você está em' });
    expect(within(trilha).getByRole('link', { name: 'Histórico' })).toHaveAttribute('href', '/historico');
  });

  it('não tem violações de acessibilidade', async () => {
    simularApi({ 'GET /api/execucoes': (url) => json(paginaDeExecucoes(MUITAS, url)) });
    const { container } = renderizarApp('/historico?pagina=2');
    await screen.findByText('Página 2 de 3');
    expect(await violacoesDeAcessibilidade(container)).toEqual([]);
  });
});

describe('Configurações', () => {
  const comChave = (origem: 'tela' | 'ambiente'): Configuracao => ({
    ...CONFIGURACAO,
    chave: { configurada: true, origem, final: 'WXYZ' },
  });

  it('fica no menu e mostra provedor, modelo e preço, sem permitir trocar o modelo', async () => {
    const usuario = userEvent.setup();
    simularApi({});
    renderizarApp();
    await usuario.click(await screen.findByRole('link', { name: 'Configurações' }));
    await screen.findByRole('heading', { name: 'Configurações' });

    expect(await screen.findByText(/Provedor:/)).toHaveTextContent(
      'Provedor: Anthropic · Modelo: claude-sonnet-5-5',
    );
    expect(screen.getByText(/US\$ 2,00 entrada · US\$ 10,00 saída/)).toBeInTheDocument();
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('não inventa preço para um modelo fora da tabela', async () => {
    simularApi({
      'GET /api/configuracao': () =>
        json({
          ...CONFIGURACAO,
          modelo: 'interno-x',
          preco_entrada_usd_mtok: null,
          preco_saida_usd_mtok: null,
        }),
    });
    renderizarApp('/configuracoes');
    expect(await screen.findByText(/Preço não informado/)).toBeInTheDocument();
  });

  it('guarda a chave, limpa o campo e só mostra os 4 últimos caracteres', async () => {
    const usuario = userEvent.setup();
    const segredo = 'sk-ant-api03-SEGREDO-que-nao-pode-aparecer-WXYZ';
    const mock = simularApi({ 'PUT /api/configuracao/chave': () => json(comChave('tela')) });
    renderizarApp('/configuracoes');
    const campo = await screen.findByLabelText('Chave de API da Anthropic');
    expect(campo).toHaveAttribute('type', 'password');
    expect(screen.getByRole('button', { name: /guardar chave/i })).toBeDisabled();

    await usuario.type(campo, `  ${segredo}  `);
    await usuario.click(screen.getByRole('button', { name: /guardar chave/i }));

    expect(await screen.findByText(/termina em/)).toHaveTextContent('termina em WXYZ');
    expect(screen.getByLabelText('Trocar a chave')).toHaveValue('');
    expect(document.body.textContent).not.toContain('SEGREDO');
    const chamada = mock.mock.calls.find(([, init]) => init?.method === 'PUT');
    expect(corpoJson(chamada?.[1])).toEqual({ chave: segredo });
    const guardado = [...Object.values(localStorage), ...Object.values(sessionStorage)].join('|');
    expect(guardado).not.toContain('SEGREDO'); // a chave nunca vai para o armazenamento do navegador
  });

  it('mostra o motivo quando a chave é recusada e mantém o que foi digitado para corrigir', async () => {
    const usuario = userEvent.setup();
    simularApi({
      'PUT /api/configuracao/chave': () =>
        json({ detail: 'a chave não parece uma chave de API da Anthropic' }, 400),
    });
    renderizarApp('/configuracoes');
    await usuario.type(await screen.findByLabelText('Chave de API da Anthropic'), 'chave-errada');
    await usuario.click(screen.getByRole('button', { name: /guardar chave/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/não parece uma chave de API/);
    expect(screen.getByLabelText('Chave de API da Anthropic')).toHaveValue('chave-errada');
  });

  it('só oferece remover a chave quando ela foi digitada na tela (a do ambiente não é do console)', async () => {
    const usuario = userEvent.setup();
    let atual: Configuracao = comChave('ambiente');
    simularApi({
      'GET /api/configuracao': () => json(atual),
      'PUT /api/configuracao/chave': () => json((atual = comChave('tela'))),
      'DELETE /api/configuracao/chave': () => json((atual = comChave('ambiente'))),
    });
    renderizarApp('/configuracoes');
    expect(await screen.findByText(/vem do ambiente do servidor/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /remover a chave/i })).not.toBeInTheDocument();

    await usuario.type(screen.getByLabelText('Trocar a chave'), 'sk-ant-api03-' + 'a'.repeat(30));
    await usuario.click(screen.getByRole('button', { name: /guardar chave/i }));
    await usuario.click(await screen.findByRole('button', { name: /remover a chave digitada/i }));
    expect(await screen.findByText(/vem do ambiente do servidor/)).toBeInTheDocument();
  });

  it('a tela Executar mostra o modelo em uso e leva às configurações', async () => {
    const usuario = userEvent.setup();
    simularApi({});
    renderizarApp();
    await escolherDocumentos(usuario, '01_a.pdf');
    const nota = await screen.findByText(/Modelo em uso:/);
    expect(nota).toHaveTextContent('modelo-de-teste');
    expect(within(nota).getByRole('link', { name: 'Configurações' })).toHaveAttribute(
      'href',
      '/configuracoes',
    );
  });

  it('não tem violações de acessibilidade', async () => {
    simularApi({});
    const { container } = renderizarApp('/configuracoes');
    await screen.findByLabelText('Chave de API da Anthropic');
    expect(await violacoesDeAcessibilidade(container)).toEqual([]);
  });
});

describe('Navegação', () => {
  it('rota desconhecida mostra página não encontrada', async () => {
    simularApi({});
    renderizarApp('/nao-existe');
    expect(await screen.findByRole('heading', { name: /página não encontrada/i })).toBeInTheDocument();
  });

  it('Sair apaga o token e volta para a tela de acesso', async () => {
    const usuario = userEvent.setup();
    simularApi({});
    renderizarApp();
    await usuario.click(await screen.findByRole('button', { name: 'Sair' }));
    expect(await screen.findByRole('heading', { name: /acesso ao console/i })).toBeInTheDocument();
    expect(sessionStorage.length).toBe(0);
  });
});

describe('Aparência', () => {
  beforeEach(() => {
    localStorage.clear();
    restaurarPreferencias();
  });

  it('troca tema e tamanho do texto, com efeito imediato e guardando a escolha', async () => {
    const usuario = userEvent.setup();
    simularApi({});
    renderizarApp();
    await usuario.click(await screen.findByRole('button', { name: 'Aparência' }));
    const dialogo = await screen.findByRole('dialog', { name: 'Aparência' });

    await usuario.click(within(dialogo).getByRole('radio', { name: /escuro/i }));
    await usuario.click(within(dialogo).getByRole('radio', { name: /muito grande/i }));
    expect(document.documentElement.dataset.tema).toBe('escuro');
    expect(document.documentElement.dataset.texto).toBe('maior');

    await usuario.click(within(dialogo).getByRole('button', { name: 'Restaurar padrão' }));
    expect(document.documentElement.dataset.texto).toBe('padrao');
    expect(within(dialogo).getByRole('radio', { name: /seguir o sistema/i })).toBeChecked();
    expect(localStorage.length).toBe(0);
  });

  it('o painel de aparência também está disponível antes do login', () => {
    simularApi({});
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole('heading', { name: /acesso ao console/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Aparência' })).toBeInTheDocument();
  });
});
