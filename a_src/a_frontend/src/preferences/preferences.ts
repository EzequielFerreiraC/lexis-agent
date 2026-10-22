/**
 * Preferências de aparência (tema e tamanho do texto). Ficam em localStorage e são aplicadas como atributos em <html>
 * (data-tema e data-texto), que o CSS usa. Só guarda preferência visual: nunca o token de acesso nem dados de documentos.
 */
export type Tema = 'sistema' | 'claro' | 'escuro';
export type TamanhoTexto = 'pequeno' | 'padrao' | 'grande' | 'maior';

export interface Preferencias {
  tema: Tema;
  texto: TamanhoTexto;
}

export const PADRAO: Preferencias = { tema: 'sistema', texto: 'padrao' };
export const TEMAS: readonly Tema[] = ['sistema', 'claro', 'escuro'];
export const TAMANHOS: readonly TamanhoTexto[] = ['pequeno', 'padrao', 'grande', 'maior'];

const CHAVE = 'lexis.preferencias';
const CONSULTA_ESCURO = '(prefers-color-scheme: dark)';

const ehTema = (v: unknown): v is Tema => TEMAS.includes(v as Tema);
const ehTamanho = (v: unknown): v is TamanhoTexto => TAMANHOS.includes(v as TamanhoTexto);

/** Lê o que foi salvo; qualquer valor ausente, corrompido ou inesperado cai no padrão. */
export function lerPreferencias(): Preferencias {
  try {
    const bruto = localStorage.getItem(CHAVE);
    if (!bruto) return PADRAO;
    const dado = JSON.parse(bruto) as Partial<Record<keyof Preferencias, unknown>>;
    return {
      tema: ehTema(dado.tema) ? dado.tema : PADRAO.tema,
      texto: ehTamanho(dado.texto) ? dado.texto : PADRAO.texto,
    };
  } catch {
    return PADRAO; // armazenamento bloqueado (janela anônima, política do navegador) ou JSON inválido
  }
}

function salvar(prefs: Preferencias): void {
  try {
    if (prefs.tema === PADRAO.tema && prefs.texto === PADRAO.texto) localStorage.removeItem(CHAVE);
    else localStorage.setItem(CHAVE, JSON.stringify(prefs));
  } catch {
    // sem armazenamento: a preferência vale só nesta sessão
  }
}

export function sistemaPrefereEscuro(): boolean {
  return typeof matchMedia === 'function' && matchMedia(CONSULTA_ESCURO).matches;
}

/** O tema efetivo: "sistema" vira claro ou escuro conforme o sistema operacional. */
export function temaEfetivo(tema: Tema): 'claro' | 'escuro' {
  if (tema === 'sistema') return sistemaPrefereEscuro() ? 'escuro' : 'claro';
  return tema;
}

export function aplicar(prefs: Preferencias, alvo: HTMLElement = document.documentElement): void {
  alvo.dataset.tema = temaEfetivo(prefs.tema);
  alvo.dataset.texto = prefs.texto;
}

type Ouvinte = () => void;
const ouvintes = new Set<Ouvinte>();
let atuais: Preferencias = PADRAO;

export function obterPreferencias(): Preferencias {
  return atuais;
}

export function assinarPreferencias(ouvinte: Ouvinte): () => void {
  ouvintes.add(ouvinte);
  return () => {
    ouvintes.delete(ouvinte);
  };
}

export function definirPreferencias(parcial: Partial<Preferencias>): void {
  atuais = { ...atuais, ...parcial };
  salvar(atuais);
  aplicar(atuais);
  ouvintes.forEach((o) => {
    o();
  });
}

export function restaurarPreferencias(): void {
  definirPreferencias(PADRAO);
}

/** Chamado uma vez antes de renderizar. Também acompanha o sistema quando o tema é "sistema". */
export function iniciarPreferencias(): void {
  atuais = lerPreferencias();
  aplicar(atuais);
  if (typeof matchMedia === 'function') {
    matchMedia(CONSULTA_ESCURO).addEventListener('change', () => {
      if (atuais.tema === 'sistema') aplicar(atuais);
    });
  }
}
