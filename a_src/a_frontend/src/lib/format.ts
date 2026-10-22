import type { CampoSaida } from '../api/types';

const MOEDAS = new Set(['valor_bruto', 'valor_liquido', 'custo_atribuido']);

/** `2026-06-12` -> `12/06/2026`, sem passar por Date (evita deslocamento de fuso). */
export function formatarDataIso(iso: string): string {
  const achado = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  return achado ? `${achado[3] ?? ''}/${achado[2] ?? ''}/${achado[1] ?? ''}` : iso;
}

export function formatarDataHora(iso: string | null | undefined): string {
  if (!iso) return '—';
  const data = new Date(iso);
  return Number.isNaN(data.getTime())
    ? iso
    : data.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'medium' });
}

/** `0.4275000000` -> `0,4275000000`: troca só o separador, preservando todas as casas (nunca arredonda). */
export function formatarDecimal(valor: string): string {
  return valor.replace('.', ',');
}

export function formatarUsd(valor: number | null | undefined): string {
  if (valor === null || valor === undefined) return 'não estimado';
  return `US$ ${valor.toLocaleString('pt-BR', { minimumFractionDigits: 4, maximumFractionDigits: 6 })}`;
}

export function formatarDuracao(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—';
  return ms < 1000
    ? `${String(ms)} ms`
    : `${(ms / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} s`;
}

export function formatarBytes(bytes: number): string {
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1).replace('.', ',')} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace('.', ',')} MB`;
}

/** Texto exibido para o valor de um campo. O valor bruto/normalizado nunca é reescrito além do separador decimal. */
export function textoDoValor(nome: string, campo: CampoSaida): string {
  if (campo.estado === 'NAO_APLICAVEL') return 'Não se aplica a este tipo de evento';
  if (campo.estado === 'PENDENTE') return campo.texto_literal ?? 'A definir';
  if (campo.estado === 'AUSENTE') return 'Não consta no aviso';
  if (campo.estado === 'INCERTO') return 'Valor não verificado';
  const valor = campo.valor;
  if (valor === null || valor === undefined) return '—';
  if (nome.startsWith('data_')) return formatarDataIso(valor);
  if (nome === 'aliquota_irrf') return formatarDecimal(campo.detalhe_valor?.percentual ?? valor);
  if (MOEDAS.has(nome)) return formatarDecimal(valor);
  return valor;
}
