import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import axe from 'axe-core';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import { App } from '../App';
import type { Amostra, Catalogo, Configuracao, ExecucaoItem, RegistroSaida, Saude } from '../api/types';
import { definirToken } from '../auth/token';
import registro05 from './fixtures/record_05.json';
import registro07 from './fixtures/record_07.json';

export const REGISTRO_05 = registro05 as unknown as RegistroSaida;
export const REGISTRO_07 = registro07 as unknown as RegistroSaida;

export const SAUDE: Saude = {
  versao_pipeline: '1.0.0',
  versoes: { regras: 'abc123', prompt: 'p1' },
  modelo: 'modelo-de-teste',
  modos: [
    { id: 'replay', disponivel: true, descricao: 'Usa as gravações locais.' },
    { id: 'auto', disponivel: true, descricao: 'Usa gravação se houver.' },
    {
      id: 'live',
      disponivel: false,
      descricao: 'Chama o modelo.',
      motivo_indisponivel: 'ANTHROPIC_API_KEY ausente',
    },
  ],
  ocr_disponivel: false,
  orcamento_tokens: 400000,
  gravacoes_simuladas: true,
  limites: { max_arquivos: 20, max_bytes_por_arquivo: 20 * 1024 * 1024 },
};

export const CATALOGO: Catalogo = {
  versao: 'teste',
  campos: ['isin', 'data_pagamento', 'valor_bruto'],
  rotulos: {
    isin: 'ISIN',
    data_pagamento: 'Data de pagamento',
    valor_bruto: 'Valor bruto por ação',
    data_com: 'Data com',
  },
  regras: {
    DATAS_PAGAMENTO_ANTES_DA_COM: { severidade: 'ERRO', descricao: 'Pagamento antes da data com' },
  },
  tipos: {
    DIVIDENDO: { rotulo: 'Dividendo', tratamento_tributario: 'isento', criticos: [], aplicabilidade: {} },
  },
};

export const CONFIGURACAO: Configuracao = {
  provedor: 'Anthropic',
  modelo: 'claude-sonnet-5-5',
  preco_entrada_usd_mtok: 2,
  preco_saida_usd_mtok: 10,
  chave: { configurada: false, origem: null, final: null },
};

export const AMOSTRAS: Amostra[] = [
  { nome: '01_a.pdf', tamanho: 2048, sha256: 'a'.repeat(64) },
  { nome: '02_b.pdf', tamanho: 4096, sha256: 'b'.repeat(64) },
];

/** Responde como o servidor: recorta `itens` com `limite`/`deslocamento` da URL e informa o total. */
export function paginaDeExecucoes(itens: ExecucaoItem[], url: URL) {
  const limite = Number(url.searchParams.get('limite') ?? 20);
  const deslocamento = Number(url.searchParams.get('deslocamento') ?? 0);
  return {
    itens: itens.slice(deslocamento, deslocamento + limite),
    total: itens.length,
    limite,
    deslocamento,
  };
}

export const json = (corpo: unknown, status = 200): Response =>
  new Response(JSON.stringify(corpo), { status, headers: { 'Content-Type': 'application/json' } });

export type ChamadaDeFetch = readonly [RequestInfo | URL, RequestInit | undefined];

export const urlDe = (entrada: RequestInfo | URL): string =>
  typeof entrada === 'string' ? entrada : entrada instanceof URL ? entrada.href : entrada.url;

export const corpoJson = (init: RequestInit | undefined): Record<string, unknown> =>
  typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : {};

type Manipulador = (url: URL, init: RequestInit | undefined) => Response | Promise<Response>;

/** Simula a API: a chave é "MÉTODO /caminho". O que não foi declarado responde 404, como o servidor real. */
export function simularApi(rotas: Record<string, Manipulador>) {
  const base: Record<string, Manipulador> = {
    'GET /api/sessao': () => json({ login_exigido: false, usuario: null, dominios_email: [] }),
    'GET /api/saude': () => json(SAUDE),
    'GET /api/catalogo': () => json(CATALOGO),
    'GET /api/amostras': () => json(AMOSTRAS),
    'GET /api/configuracao': () => json(CONFIGURACAO),
    'GET /api/execucoes': (url) => json(paginaDeExecucoes([], url)),
  };
  const todas = { ...base, ...rotas };
  const mock = vi.fn((entrada: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(urlDe(entrada), 'http://127.0.0.1');
    const manipulador = todas[`${init?.method ?? 'GET'} ${url.pathname}`];
    return Promise.resolve(manipulador ? manipulador(url, init) : json({ detail: 'não encontrado' }, 404));
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

export function renderizarApp(caminho = '/') {
  definirToken('token-de-teste');
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const envolver = (ui: ReactElement) => (
    <QueryClientProvider client={cliente}>
      <MemoryRouter initialEntries={[caminho]}>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
  return render(envolver(<App />));
}

/** Contraste fica de fora porque o jsdom não calcula estilos; o restante das regras do axe é aplicado. */
export async function violacoesDeAcessibilidade(raiz: Element): Promise<string[]> {
  const resultado = await axe.run(raiz, { rules: { 'color-contrast': { enabled: false } } });
  return resultado.violations.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join(' | ')})`,
  );
}
