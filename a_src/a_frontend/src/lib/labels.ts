import type {
  Catalogo,
  Decisao,
  DecisaoHumana,
  EstadoCampo,
  EstadoJob,
  Modo,
  Nivel,
  Severidade,
  TipoAcao,
} from '../api/types';
import type { NomeIcone } from '../components/Icon';

export type Tom = 'sucesso' | 'atencao' | 'erro' | 'info' | 'neutro';

export const ROTULO_DECISAO: Record<Decisao, string> = {
  APROVADO_AUTO: 'Aprovado automaticamente',
  AGUARDA_EMISSOR: 'Aguardando emissor',
  REVISAO_HUMANA: 'Revisão humana',
  FALHA_PROCESSAMENTO: 'Falha no processamento',
};
export const TOM_DECISAO: Record<Decisao, Tom> = {
  APROVADO_AUTO: 'sucesso',
  AGUARDA_EMISSOR: 'info',
  REVISAO_HUMANA: 'atencao',
  FALHA_PROCESSAMENTO: 'erro',
};
export const ICONE_DECISAO: Record<Decisao, NomeIcone> = {
  APROVADO_AUTO: 'certo',
  AGUARDA_EMISSOR: 'relogio',
  REVISAO_HUMANA: 'alerta',
  FALHA_PROCESSAMENTO: 'erro',
};
export const ROTULO_DECISAO_HUMANA: Record<DecisaoHumana, string> = {
  APROVADO_NA_REVISAO: 'Aprovado na revisão',
  REJEITADO_NA_REVISAO: 'Rejeitado na revisão',
};
export const TOM_DECISAO_HUMANA: Record<DecisaoHumana, Tom> = {
  APROVADO_NA_REVISAO: 'sucesso',
  REJEITADO_NA_REVISAO: 'erro',
};
/** Ícone padrão de cada tom, para selos e avisos. */
export const ICONE_TOM: Record<Tom, NomeIcone> = {
  sucesso: 'certo',
  atencao: 'alerta',
  erro: 'erro',
  info: 'info',
  neutro: 'info',
};
/** O que exige atuação aparece primeiro. */
export const PRIORIDADE_DECISAO: Record<Decisao, number> = {
  REVISAO_HUMANA: 0,
  FALHA_PROCESSAMENTO: 1,
  AGUARDA_EMISSOR: 2,
  APROVADO_AUTO: 3,
};
export const DECISOES: Decisao[] = [
  'REVISAO_HUMANA',
  'FALHA_PROCESSAMENTO',
  'AGUARDA_EMISSOR',
  'APROVADO_AUTO',
];

export const ROTULO_NIVEL: Record<Nivel, string> = {
  ALTA: 'Confiança alta',
  MEDIA: 'Confiança média',
  BAIXA: 'Confiança baixa',
};
export const TOM_NIVEL: Record<Nivel, Tom> = { ALTA: 'sucesso', MEDIA: 'atencao', BAIXA: 'erro' };

export const ROTULO_ESTADO_CAMPO: Record<EstadoCampo, string> = {
  EXTRAIDO: 'Extraído',
  NAO_APLICAVEL: 'Não se aplica',
  AUSENTE: 'Ausente',
  PENDENTE: 'Pendente no aviso',
  INCERTO: 'Incerto',
};
export const TOM_ESTADO_CAMPO: Record<EstadoCampo, Tom> = {
  EXTRAIDO: 'neutro',
  NAO_APLICAVEL: 'neutro',
  AUSENTE: 'erro',
  PENDENTE: 'info',
  INCERTO: 'erro',
};

export const ROTULO_SEVERIDADE: Record<Severidade, string> = {
  ERRO: 'Erro',
  AVISO: 'Aviso',
  INFO: 'Informação',
};
export const TOM_SEVERIDADE: Record<Severidade, Tom> = { ERRO: 'erro', AVISO: 'atencao', INFO: 'info' };

export const ROTULO_ACAO: Record<TipoAcao, string> = {
  CORRIGIR_EXTRACAO: 'Corrigir a extração',
  RESOLVER_INCONSISTENCIA: 'Resolver inconsistência',
  CADASTRAR_EMISSOR: 'Cadastrar emissor',
  AGUARDAR_AVISO_COMPLEMENTAR: 'Aguardar aviso complementar',
  CONFERIR_CLASSIFICACAO: 'Conferir classificação',
  VERIFICAR_SEGURANCA: 'Verificar segurança',
  REPROCESSAR: 'Reprocessar',
};

export const ROTULO_ESTADO_JOB: Record<EstadoJob, string> = {
  NA_FILA: 'Na fila',
  EM_ANDAMENTO: 'Em andamento',
  CONCLUIDA: 'Concluída',
  FALHOU: 'Falhou',
};
export const TOM_ESTADO_JOB: Record<EstadoJob, Tom> = {
  NA_FILA: 'neutro',
  EM_ANDAMENTO: 'info',
  CONCLUIDA: 'sucesso',
  FALHOU: 'erro',
};

/** A tela oferece só demonstração (sem chave) e extração com IA (com chave); `auto` aparece apenas em execuções antigas. */
export const ROTULO_MODO: Record<Modo, string> = {
  replay: 'Demonstração',
  auto: 'Automático',
  live: 'Extração com IA',
};
export const ICONE_MODO: Record<Modo, NomeIcone> = { replay: 'historico', auto: 'raio', live: 'chip' };

export const ROTULO_DISPOSICAO: Record<string, string> = {
  PROCESSADO: 'Processado',
  REUTILIZADO: 'Reutilizado',
  DUPLICADO_NO_LOTE: 'Duplicado no lote',
  NAO_PROCESSADO: 'Não processado (circuito aberto)',
};

export const ROTULO_GOLDEN: Record<string, string> = {
  MATCH: 'Confirmado na base',
  PARTIAL_MISMATCH: 'Diverge da base',
  NOT_FOUND: 'Fora da base',
  AMBIGUOUS: 'Ambíguo na base',
  NAO_AVALIADO: 'Não avaliado',
};
export const TOM_GOLDEN: Record<string, Tom> = {
  MATCH: 'sucesso',
  PARTIAL_MISMATCH: 'erro',
  NOT_FOUND: 'erro',
  AMBIGUOUS: 'erro',
  NAO_AVALIADO: 'neutro',
};

export const ROTULO_NATUREZA: Record<string, string> = {
  LITERAL: 'Literal do documento',
  DERIVADO: 'Derivado pelo código',
};

export const GRUPOS_DE_CAMPOS: { titulo: string; campos: string[] }[] = [
  { titulo: 'Evento', campos: ['tipo_evento'] },
  { titulo: 'Identificação', campos: ['emissor', 'cnpj', 'isin', 'ticker', 'classe_acao'] },
  {
    titulo: 'Datas',
    campos: ['data_aprovacao', 'data_com', 'data_ex', 'data_pagamento', 'data_credito_ativos'],
  },
  {
    titulo: 'Valores e tributação',
    campos: [
      'valor_bruto',
      'aliquota_irrf',
      'valor_liquido',
      'custo_atribuido',
      'moeda',
      'observacao_tributaria',
    ],
  },
  { titulo: 'Proporção', campos: ['proporcao'] },
];

export function rotuloDoCampo(catalogo: Catalogo | undefined, campo: string): string {
  if (campo === 'tipo_evento') return 'Tipo de evento';
  return catalogo?.rotulos[campo] ?? campo;
}

export function descricaoDaRegra(catalogo: Catalogo | undefined, id: string): string {
  return catalogo?.regras[id]?.descricao ?? id;
}

export const rotuloDe = <K extends string>(mapa: Record<K, string>, chave: string): string =>
  (mapa as Record<string, string | undefined>)[chave] ?? chave;
