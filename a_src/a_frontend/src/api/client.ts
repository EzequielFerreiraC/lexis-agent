import { obterToken } from '../auth/token';
import type {
  Amostra,
  CadastroNovo,
  Catalogo,
  Configuracao,
  ExecucaoNova,
  ExecucaoResumo,
  NomeRelatorio,
  PaginaExecucoes,
  PaginaMeta,
  RegistroSaida,
  RevisaoHumana,
  RevisaoNova,
  Saude,
  SessaoInfo,
  UploadResposta,
} from './types';

/** No 401, o que falta: o token da subida do servidor (Bearer) ou a sessão do usuário (login, só com banco). */
export type Exige = 'token' | 'sessao' | null;

export class ErroApi extends Error {
  readonly status: number;
  readonly exige: Exige;

  constructor(status: number, mensagem: string, exige: Exige = null) {
    super(mensagem);
    this.name = 'ErroApi';
    this.status = status;
    this.exige = exige;
  }
}

function oQueFalta(resposta: Response): Exige {
  if (resposta.status !== 401) return null;
  return resposta.headers.get('WWW-Authenticate')?.toLowerCase() === 'session' ? 'sessao' : 'token';
}

function extrairDetalhe(corpo: unknown): string | null {
  if (typeof corpo !== 'object' || corpo === null || !('detail' in corpo)) return null;
  const detalhe = corpo.detail;
  if (typeof detalhe === 'string') return detalhe;
  return Array.isArray(detalhe) ? 'dados da requisição inválidos' : null;
}

async function mensagemDeErro(resposta: Response): Promise<string> {
  try {
    return extrairDetalhe(await resposta.json()) ?? `Erro ${resposta.status}`;
  } catch {
    return `Erro ${resposta.status}`;
  }
}

async function chamar(caminho: string, init: RequestInit = {}): Promise<Response> {
  const token = obterToken();
  const resposta = await fetch(caminho, {
    ...init,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers as Record<string, string>),
    },
    cache: 'no-store',
    // same-origin: o cookie da sessão (HttpOnly, SameSite=Strict, só em /api) vai junto; nunca para outro site
    credentials: 'same-origin',
    referrerPolicy: 'no-referrer',
  });
  if (!resposta.ok) throw new ErroApi(resposta.status, await mensagemDeErro(resposta), oQueFalta(resposta));
  return resposta;
}

async function json<T>(caminho: string, init?: RequestInit): Promise<T> {
  return (await (await chamar(caminho, init)).json()) as T;
}

const enc = encodeURIComponent;
const JSON_HEADERS = { 'Content-Type': 'application/json' };

export const api = {
  saude: () => json<Saude>('/api/saude'),
  catalogo: () => json<Catalogo>('/api/catalogo'),
  amostras: () => json<Amostra[]>('/api/amostras'),

  sessao: () => json<SessaoInfo>('/api/sessao'),
  entrar: (login: string, senha: string) =>
    json<SessaoInfo>('/api/sessao', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ login, senha }),
    }),
  cadastrar: (pedido: CadastroNovo) =>
    json<SessaoInfo>('/api/usuarios', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(pedido),
    }),
  sair: () => json<SessaoInfo>('/api/sessao', { method: 'DELETE' }),

  configuracao: () => json<Configuracao>('/api/configuracao'),
  guardarChave: (chave: string) =>
    json<Configuracao>('/api/configuracao/chave', {
      method: 'PUT',
      headers: JSON_HEADERS,
      body: JSON.stringify({ chave }),
    }),
  removerChave: () => json<Configuracao>('/api/configuracao/chave', { method: 'DELETE' }),

  enviar: (arquivos: File[]) => {
    const corpo = new FormData();
    arquivos.forEach((arquivo) => {
      corpo.append('arquivos', arquivo, arquivo.name);
    });
    return json<UploadResposta>('/api/uploads', { method: 'POST', body: corpo });
  },

  iniciarExecucao: (pedido: ExecucaoNova) =>
    json<ExecucaoResumo>('/api/execucoes', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(pedido),
    }),
  execucoes: (limite: number, deslocamento: number) =>
    json<PaginaExecucoes>(`/api/execucoes?limite=${String(limite)}&deslocamento=${String(deslocamento)}`),
  execucao: (id: string) => json<ExecucaoResumo>(`/api/execucoes/${enc(id)}`),

  documento: (id: string, nome: string) =>
    json<RegistroSaida>(`/api/execucoes/${enc(id)}/documentos/${enc(nome)}`),
  revisar: (id: string, nome: string, pedido: RevisaoNova) =>
    json<RevisaoHumana>(`/api/execucoes/${enc(id)}/documentos/${enc(nome)}/revisao`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(pedido),
    }),
  pagina: (id: string, nome: string, numero: number) =>
    json<PaginaMeta>(`/api/execucoes/${enc(id)}/documentos/${enc(nome)}/paginas/${String(numero)}`),
  /** A imagem exige o cabeçalho de autorização, então é buscada como Blob (um <img src> não consegue enviá-lo). */
  imagemPagina: async (id: string, nome: string, numero: number): Promise<Blob> =>
    (
      await chamar(`/api/execucoes/${enc(id)}/documentos/${enc(nome)}/paginas/${String(numero)}/imagem`)
    ).blob(),
  relatorio: async (id: string, arquivo: NomeRelatorio): Promise<Blob> =>
    (await chamar(`/api/execucoes/${enc(id)}/relatorios/${enc(arquivo)}`)).blob(),
};
