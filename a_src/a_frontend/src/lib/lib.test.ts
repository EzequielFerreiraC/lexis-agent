import { describe, expect, it } from 'vitest';
import type { CampoSaida } from '../api/types';
import {
  formatarBytes,
  formatarDataIso,
  formatarDecimal,
  formatarDuracao,
  formatarUsd,
  textoDoValor,
} from './format';
import { ehDicionario, listaDeTextos, paraTexto } from './record';
import { DECISOES, GRUPOS_DE_CAMPOS, PRIORIDADE_DECISAO, rotuloDoCampo } from './labels';

const campo = (parcial: Partial<CampoSaida>): CampoSaida => ({
  estado: 'EXTRAIDO',
  confianca: { nivel: 'ALTA', justificativa: '', motivos: [] },
  ...parcial,
});

describe('formatação', () => {
  it('converte data ISO sem passar por Date (sem deslocamento de fuso)', () => {
    expect(formatarDataIso('2026-06-12')).toBe('12/06/2026');
    expect(formatarDataIso('texto')).toBe('texto');
  });

  it('só troca o separador decimal, preservando todas as casas', () => {
    expect(formatarDecimal('0.4275000000')).toBe('0,4275000000');
  });

  it('formata duração, custo e tamanho', () => {
    expect(formatarDuracao(null)).toBe('—');
    expect(formatarDuracao(850)).toBe('850 ms');
    expect(formatarDuracao(1330)).toBe('1,3 s');
    expect(formatarUsd(null)).toBe('não estimado');
    expect(formatarUsd(0)).toContain('US$');
    expect(formatarBytes(512)).toBe('512 B');
    expect(formatarBytes(2048)).toBe('2,0 KB');
  });

  it('mostra texto próprio para cada estado de campo, sem inventar valor', () => {
    expect(textoDoValor('data_ex', campo({ estado: 'NAO_APLICAVEL' }))).toMatch(/não se aplica/i);
    expect(textoDoValor('data_pagamento', campo({ estado: 'PENDENTE', texto_literal: 'a definir' }))).toBe(
      'a definir',
    );
    expect(textoDoValor('valor_bruto', campo({ estado: 'AUSENTE' }))).toMatch(/não consta/i);
    expect(textoDoValor('valor_bruto', campo({ estado: 'INCERTO' }))).toMatch(/não verificado/i);
    expect(textoDoValor('data_com', campo({ valor: '2026-07-15' }))).toBe('15/07/2026');
    expect(textoDoValor('valor_bruto', campo({ valor: '0.3100000000' }))).toBe('0,3100000000');
    expect(
      textoDoValor('aliquota_irrf', campo({ valor: '0.15', detalhe_valor: { percentual: '15.0' } })),
    ).toBe('15,0');
    expect(textoDoValor('isin', campo({ valor: 'BRAURSACNOR4' }))).toBe('BRAURSACNOR4');
  });
});

describe('leitura segura do registro', () => {
  it('reconhece só objetos simples', () => {
    expect(ehDicionario({})).toBe(true);
    expect(ehDicionario([])).toBe(false);
    expect(ehDicionario(null)).toBe(false);
  });

  it('converte qualquer valor em texto sem HTML', () => {
    expect(paraTexto(null)).toBe('—');
    expect(paraTexto(3)).toBe('3');
    expect(paraTexto({ a: 1 })).toBe('{"a":1}');
    expect(listaDeTextos({ x: ['a', 1, 'b'] }, 'x')).toEqual(['a', 'b']);
  });
});

describe('rótulos e ordenação', () => {
  it('põe o que exige atuação humana primeiro', () => {
    const ordenadas = [...DECISOES].sort((a, b) => PRIORIDADE_DECISAO[a] - PRIORIDADE_DECISAO[b]);
    expect(ordenadas[0]).toBe('REVISAO_HUMANA');
    expect(ordenadas.at(-1)).toBe('APROVADO_AUTO');
  });

  it('cai no nome técnico quando o catálogo não tem rótulo', () => {
    expect(rotuloDoCampo(undefined, 'isin')).toBe('isin');
    expect(rotuloDoCampo(undefined, 'tipo_evento')).toBe('Tipo de evento');
  });

  it('não repete campos entre grupos', () => {
    const todos = GRUPOS_DE_CAMPOS.flatMap((g) => g.campos);
    expect(new Set(todos).size).toBe(todos.length);
  });
});
