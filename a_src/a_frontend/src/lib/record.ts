/*
 * Leitura segura das seções livres do registro (`documento`, `evento`, `auditoria`), tipadas como
 * `{ [chave]: unknown }` no contrato. Nada aqui assume formato: cada leitor valida o que recebe.
 */
type Dicionario = Record<string, unknown>;

export const ehDicionario = (valor: unknown): valor is Dicionario =>
  typeof valor === 'object' && valor !== null && !Array.isArray(valor);

export function texto(origem: Dicionario, chave: string): string | null {
  const valor = origem[chave];
  return typeof valor === 'string' ? valor : null;
}

export function numero(origem: Dicionario, chave: string): number | null {
  const valor = origem[chave];
  return typeof valor === 'number' ? valor : null;
}

export function lista(origem: Dicionario, chave: string): Dicionario[] {
  const valor = origem[chave];
  return Array.isArray(valor) ? valor.filter(ehDicionario) : [];
}

export function dicionario(origem: Dicionario, chave: string): Dicionario {
  const valor = origem[chave];
  return ehDicionario(valor) ? valor : {};
}

export function listaDeTextos(origem: Dicionario, chave: string): string[] {
  const valor = origem[chave];
  return Array.isArray(valor) ? valor.filter((item): item is string => typeof item === 'string') : [];
}

/** Converte qualquer valor para texto de exibição, sem HTML. */
export function paraTexto(valor: unknown): string {
  if (valor === null || valor === undefined) return '—';
  if (typeof valor === 'string') return valor;
  if (typeof valor === 'number' || typeof valor === 'boolean') return String(valor);
  return JSON.stringify(valor);
}
