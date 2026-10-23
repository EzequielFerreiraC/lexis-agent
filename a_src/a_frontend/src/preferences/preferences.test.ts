import { beforeEach, describe, expect, it } from 'vitest';
import {
  PADRAO,
  aplicar,
  definirPreferencias,
  iniciarPreferencias,
  lerPreferencias,
  obterPreferencias,
  restaurarPreferencias,
  temaEfetivo,
} from './preferences';

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.tema;
  delete document.documentElement.dataset.texto;
  iniciarPreferencias();
});

describe('preferências de aparência', () => {
  it('sem nada salvo usa o padrão (tema do sistema, texto padrão)', () => {
    expect(lerPreferencias()).toEqual(PADRAO);
    expect(document.documentElement.dataset.texto).toBe('padrao');
  });

  it('aplica e guarda as escolhas', () => {
    definirPreferencias({ tema: 'escuro', texto: 'grande' });
    expect(document.documentElement.dataset.tema).toBe('escuro');
    expect(document.documentElement.dataset.texto).toBe('grande');
    expect(lerPreferencias()).toEqual({ tema: 'escuro', texto: 'grande' });
  });

  it('voltar ao padrão apaga o que foi guardado', () => {
    definirPreferencias({ tema: 'claro' });
    restaurarPreferencias();
    expect(localStorage.length).toBe(0);
    expect(obterPreferencias()).toEqual(PADRAO);
  });

  it('valores corrompidos ou desconhecidos caem no padrão', () => {
    localStorage.setItem('lexis.preferencias', '{"tema":"roxo","texto":"gigante"}');
    expect(lerPreferencias()).toEqual(PADRAO);
    localStorage.setItem('lexis.preferencias', 'isto não é json');
    expect(lerPreferencias()).toEqual(PADRAO);
  });

  it('tema "sistema" vira claro quando o sistema não informa preferência', () => {
    expect(temaEfetivo('sistema')).toBe('claro');
    expect(temaEfetivo('escuro')).toBe('escuro');
    const alvo = document.createElement('div');
    aplicar({ tema: 'sistema', texto: 'maior' }, alvo);
    expect(alvo.dataset.tema).toBe('claro');
    expect(alvo.dataset.texto).toBe('maior');
  });
});
