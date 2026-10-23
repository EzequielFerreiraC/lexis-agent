import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Dica } from './Hint';

describe('Dica', () => {
  it('liga o gatilho ao popover nativo e nomeia os dois', () => {
    render(
      <Dica rotulo="OCR local" titulo="O que é OCR">
        <p>Leitura do texto de PDFs escaneados.</p>
      </Dica>,
    );
    const gatilho = screen.getByRole('button', { name: 'Sobre: OCR local' });
    const painel = document.getElementById(gatilho.getAttribute('popovertarget') ?? '');
    expect(painel).toHaveAttribute('popover', 'auto');
    expect(painel).toHaveAttribute('aria-label', 'O que é OCR');
    expect(painel).toHaveTextContent('Leitura do texto de PDFs escaneados.');
  });
});
