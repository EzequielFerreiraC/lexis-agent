import type { components } from './schema';

type S = components['schemas'];

export type Saude = S['Saude'];
export type Catalogo = S['Catalogo'];
export type Amostra = S['Amostra'];
export type UploadResposta = S['UploadResposta'];
export type ExecucaoNova = S['ExecucaoNova'];
export type ExecucaoItem = S['ExecucaoItem'];
export type ExecucaoResumo = S['ExecucaoResumo'];
export type DocumentoResumo = S['DocumentoResumo'];
export type RegistroSaida = S['RegistroSaida'];
export type CampoSaida = S['CampoSaida'];
export type Evidencia = S['Evidencia'];
export type Ficha = S['Ficha'];
export type RegraResultado = S['RegraResultado'];
export type ValidacaoGolden = S['ValidacaoGolden'];
export type PaginaMeta = S['PaginaMeta'];
export type PaginaExecucoes = S['PaginaExecucoes'];
export type ModoInfo = S['ModoInfo'];
export type Configuracao = S['Configuracao'];
export type RevisaoNova = S['RevisaoNova'];
export type SessaoInfo = S['SessaoInfo'];
export type UsuarioInfo = S['UsuarioInfo'];
export type CadastroNovo = S['CadastroNovo'];
export type RevisaoHumana = S['RevisaoHumana'];
export type ParaAprovar = S['ParaAprovar'];
export type PassoParaAprovar = S['PassoParaAprovar'];

export type Modo = ExecucaoItem['modo'];
export type EstadoJob = ExecucaoItem['estado'];
export type Decisao = DocumentoResumo['estado'];
export type Nivel = CampoSaida['confianca']['nivel'];
export type EstadoCampo = CampoSaida['estado'];
export type Severidade = RegraResultado['severidade'];
export type TipoAcao = Ficha['tipo_acao'];
export type DecisaoHumana = RevisaoHumana['decisao'];

export const RELATORIOS = [
  'relatorio_excecoes.md',
  'relatorio_excecoes.json',
  'resumo_execucao.json',
  'auditoria.jsonl',
] as const;
export type NomeRelatorio = (typeof RELATORIOS)[number];
