import { keepPreviousData, useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { api } from './client';
import type { Configuracao, EstadoJob, ExecucaoNova, RevisaoNova, SessaoInfo } from './types';

const EM_ANDAMENTO: EstadoJob[] = ['NA_FILA', 'EM_ANDAMENTO'];
export const emAndamento = (estado: EstadoJob | undefined): boolean =>
  !!estado && EM_ANDAMENTO.includes(estado);

export const useSaude = () => useQuery({ queryKey: ['saude'], queryFn: api.saude, staleTime: 60_000 });
export const useCatalogo = () =>
  useQuery({ queryKey: ['catalogo'], queryFn: api.catalogo, staleTime: Infinity });
export const useConfiguracao = () =>
  useQuery({ queryKey: ['configuracao'], queryFn: api.configuracao, staleTime: 60_000 });
/** Uma página do histórico, mais recentes primeiro. Ao trocar de página, a anterior fica na tela até a nova chegar. */
export const useExecucoes = (limite: number, deslocamento = 0) =>
  useQuery({
    queryKey: ['execucoes', limite, deslocamento],
    queryFn: () => api.execucoes(limite, deslocamento),
    placeholderData: keepPreviousData,
  });

/** Consulta a execução a cada segundo enquanto ela não terminou. */
export const useExecucao = (id: string) =>
  useQuery({
    queryKey: ['execucao', id],
    queryFn: () => api.execucao(id),
    refetchInterval: (consulta) => (emAndamento(consulta.state.data?.estado) ? 1000 : false),
  });

export const useRegistro = (id: string, nome: string) =>
  useQuery({ queryKey: ['registro', id, nome], queryFn: () => api.documento(id, nome), staleTime: Infinity });

export const usePaginaMeta = (id: string, nome: string, numero: number) =>
  useQuery({
    queryKey: ['pagina', id, nome, numero],
    queryFn: () => api.pagina(id, nome, numero),
    staleTime: Infinity,
  });

/** Busca a imagem com autorização e devolve uma URL local (blob:) que é liberada ao desmontar. */
/** Devolve a página como data: URL (permitida pela CSP, sem blob: para liberar nem efeito colateral na renderização). */
async function blobParaDataUrl(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binario = '';
  for (const byte of bytes) binario += String.fromCharCode(byte);
  return `data:${blob.type || 'image/png'};base64,${btoa(binario)}`;
}

export function useImagemPagina(
  id: string,
  nome: string,
  numero: number,
): { url: string | null; erro: boolean } {
  const consulta = useQuery({
    queryKey: ['imagem', id, nome, numero],
    queryFn: async () => blobParaDataUrl(await api.imagemPagina(id, nome, numero)),
    staleTime: Infinity,
  });
  return { url: consulta.data ?? null, erro: consulta.isError };
}

export type PedidoDeExecucao = Omit<ExecucaoNova, 'upload_id'> & { arquivosParaEnviar?: File[] };

/** Envia os PDFs (se houver) e inicia a execução. */
export function useIniciarExecucao() {
  const clienteDeConsultas = useQueryClient();
  return useMutation({
    mutationFn: async ({ arquivosParaEnviar, ...pedido }: PedidoDeExecucao) => {
      if (pedido.origem === 'upload') {
        const envio = await api.enviar(arquivosParaEnviar ?? []);
        return api.iniciarExecucao({ ...pedido, upload_id: envio.id, arquivos: null });
      }
      return api.iniciarExecucao(pedido);
    },
    onSuccess: () => clienteDeConsultas.invalidateQueries({ queryKey: ['execucoes'] }),
  });
}

/** A decisão humana fica no resumo da execução (o registro do pipeline não muda): atualiza só a execução. */
export function useRevisar(id: string, nome: string) {
  const clienteDeConsultas = useQueryClient();
  return useMutation({
    mutationFn: (pedido: RevisaoNova) => api.revisar(id, nome, pedido),
    onSuccess: () => clienteDeConsultas.invalidateQueries({ queryKey: ['execucao', id] }),
  });
}

/** A chave muda o que `/api/saude` informa (modelo ativo, extração com IA disponível): atualiza as duas. */
function useMutacaoDeConfiguracao<V>(chamar: (valor: V) => Promise<Configuracao>) {
  const clienteDeConsultas = useQueryClient();
  return useMutation({
    mutationFn: chamar,
    onSuccess: (nova) => {
      clienteDeConsultas.setQueryData(['configuracao'], nova);
      return clienteDeConsultas.invalidateQueries({ queryKey: ['saude'] });
    },
  });
}

export const useSessao = () => useQuery({ queryKey: ['sessao'], queryFn: api.sessao, staleTime: 60_000 });

/** Entrar, criar conta e sair trocam quem está logado: tudo o que estava em cache era de outra sessão e é descartado. */
function useMutacaoDeSessao<V>(chamar: (valor: V) => Promise<SessaoInfo>) {
  const clienteDeConsultas = useQueryClient();
  return useMutation({
    mutationFn: chamar,
    onSuccess: (nova) => {
      clienteDeConsultas.removeQueries({ predicate: (q) => q.queryKey[0] !== 'sessao' });
      clienteDeConsultas.setQueryData(['sessao'], nova);
    },
  });
}

export const useEntrar = () =>
  useMutacaoDeSessao(({ login, senha }: { login: string; senha: string }) => api.entrar(login, senha));
export const useCadastrar = () => useMutacaoDeSessao(api.cadastrar);
export const useSair = () => useMutacaoDeSessao(() => api.sair());

export const useGuardarChave = () => useMutacaoDeConfiguracao((chave: string) => api.guardarChave(chave));
export const useRemoverChave = () => useMutacaoDeConfiguracao(() => api.removerChave());
