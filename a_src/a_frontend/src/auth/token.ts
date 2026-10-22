/*
 * Token de acesso da API local.
 * Chega no fragmento da URL (#token=...), que o navegador nunca envia ao servidor nem registra em logs. É movido para
 * sessionStorage (some ao fechar a aba) e removido da barra de endereço. Nunca vai em query string.
 */
const CHAVE = 'lexis.token';
const ouvintes = new Set<() => void>();

function notificar(): void {
  ouvintes.forEach((ouvinte) => {
    ouvinte();
  });
}

export function obterToken(): string | null {
  return sessionStorage.getItem(CHAVE);
}

export function definirToken(token: string): void {
  sessionStorage.setItem(CHAVE, token.trim());
  notificar();
}

export function limparToken(): void {
  sessionStorage.removeItem(CHAVE);
  notificar();
}

export function assinarToken(ouvinte: () => void): () => void {
  ouvintes.add(ouvinte);
  return () => {
    ouvintes.delete(ouvinte);
  };
}

export function extrairTokenDoFragmento(hash: string): string | null {
  const achado = /(?:^#|&)token=([^&]+)/.exec(hash);
  const bruto = achado?.[1];
  if (!bruto) return null;
  try {
    return decodeURIComponent(bruto);
  } catch {
    return null;
  }
}

/** Chamar uma vez ao iniciar: guarda o token do fragmento e limpa a URL. */
export function iniciarToken(): void {
  const token = extrairTokenDoFragmento(window.location.hash);
  if (token) {
    sessionStorage.setItem(CHAVE, token);
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
    notificar();
  }
}
