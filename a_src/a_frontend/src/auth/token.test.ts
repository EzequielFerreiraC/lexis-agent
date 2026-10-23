import { describe, expect, it } from 'vitest';
import {
  assinarToken,
  definirToken,
  extrairTokenDoFragmento,
  iniciarToken,
  limparToken,
  obterToken,
} from './token';

describe('token de acesso', () => {
  it('extrai o token do fragmento', () => {
    expect(extrairTokenDoFragmento('#token=abc_DEF-123')).toBe('abc_DEF-123');
    expect(extrairTokenDoFragmento('#x=1&token=zzz')).toBe('zzz');
  });

  it('ignora fragmento sem token ou malformado', () => {
    expect(extrairTokenDoFragmento('')).toBeNull();
    expect(extrairTokenDoFragmento('#token=')).toBeNull();
    expect(extrairTokenDoFragmento('#token=%E0%A4%A')).toBeNull();
    expect(extrairTokenDoFragmento('#outro=1')).toBeNull();
  });

  it('move o token do fragmento para a sessão e limpa a barra de endereço', () => {
    window.history.replaceState(null, '', '/execucoes#token=meu-token');
    iniciarToken();
    expect(obterToken()).toBe('meu-token');
    expect(window.location.hash).toBe('');
    expect(window.location.pathname).toBe('/execucoes');
  });

  it('guarda só em sessionStorage (nunca localStorage)', () => {
    definirToken('  abc  ');
    expect(obterToken()).toBe('abc');
    expect(localStorage.length).toBe(0);
  });

  it('notifica quem assina quando o token muda', () => {
    let chamadas = 0;
    const cancelar = assinarToken(() => {
      chamadas += 1;
    });
    definirToken('x');
    limparToken();
    cancelar();
    definirToken('y');
    expect(chamadas).toBe(2);
    expect(obterToken()).toBe('y');
  });
});
