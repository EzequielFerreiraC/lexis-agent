import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { PaginaComDestaque, caixaEmPorcentagem } from './HighlightedPage';
import { json, simularApi } from '../test/util';

describe('caixaEmPorcentagem', () => {
  it('converte pontos do PDF (origem no topo) em porcentagem da página', () => {
    expect(caixaEmPorcentagem([60, 80, 180, 120], 600, 800)).toEqual({
      left: '10.000%',
      top: '10.000%',
      width: '20.000%',
      height: '5.000%',
    });
  });

  it('não desenha nada sem bbox válida ou sem dimensões', () => {
    expect(caixaEmPorcentagem(null, 600, 800)).toBeNull();
    expect(caixaEmPorcentagem([1, 2, 3], 600, 800)).toBeNull();
    expect(caixaEmPorcentagem([1, 2, 3, 4], 0, 800)).toBeNull();
  });
});

describe('PaginaComDestaque', () => {
  const renderizar = (pagina: number, evidenciaPagina: number) => {
    simularApi({
      'GET /api/execucoes/abc/documentos/d.pdf/paginas/1': () =>
        json({ numero: 1, total_paginas: 2, largura_pt: 600, altura_pt: 800 }),
      'GET /api/execucoes/abc/documentos/d.pdf/paginas/1/imagem': () =>
        new Response(new Uint8Array([1, 2, 3]), { headers: { 'Content-Type': 'image/png' } }),
    });
    return render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <PaginaComDestaque
          execucaoId="abc"
          nome="d.pdf"
          numero={pagina}
          total={2}
          aoMudarPagina={() => undefined}
          destaque={{
            rotulo: 'Valor bruto',
            evidencia: {
              pagina: evidenciaPagina,
              trecho: 'R$ 1,00',
              bbox: [10, 10, 50, 20],
              fonte: 'TEXTO_NATIVO',
            },
          }}
        />
      </QueryClientProvider>,
    );
  };

  it('usa data: URL na imagem (a CSP não permite abrir o PDF nem depende de blob:)', async () => {
    renderizar(1, 1);
    const imagem = await screen.findByRole('img', { name: /página 1/i });
    expect(imagem.getAttribute('src')).toMatch(/^data:image\/png;base64,/);
    await waitFor(() => {
      expect(screen.getByTestId('destaque-bbox')).toBeInTheDocument();
    });
  });

  it('avisa quando o campo está em outra página, sem destacar a atual', async () => {
    renderizar(1, 2);
    expect(await screen.findByText(/está na página 2/i)).toBeInTheDocument();
    expect(screen.queryByTestId('destaque-bbox')).not.toBeInTheDocument();
  });
});
