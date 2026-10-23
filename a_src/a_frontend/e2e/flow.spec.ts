import AxeBuilder from '@axe-core/playwright';
import { readdirSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const TOKEN = 'token-e2e-playwright-0123456789';
// os PDFs do case têm leitura gravada em c_replay/: a demonstração os processa sem chave de API
const PASTA_PDFS = join(import.meta.dirname, '../../../f_data/a_input');
const PDFS = readdirSync(PASTA_PDFS)
  .filter((n) => n.endsWith('.pdf'))
  .map((n) => join(PASTA_PDFS, n));

function vigiarCsp(page: Page): string[] {
  const violacoes: string[] = [];
  page.on('console', (mensagem) => {
    if (/content security policy/i.test(mensagem.text())) violacoes.push(mensagem.text());
  });
  page.on('pageerror', (erro) => violacoes.push(erro.message));
  return violacoes;
}

async function semViolacoesDeAcessibilidade(page: Page) {
  const resultado = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(
    resultado.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`),
  ).toEqual([]);
}

test('sem token só aparece a tela de acesso', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Acesso ao console' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Principal' })).toHaveCount(0);
});

test('token errado é recusado pela API e volta para a tela de acesso', async ({ page }) => {
  await page.goto('/#token=errado');
  await expect(page.getByRole('heading', { name: 'Acesso ao console' })).toBeVisible();
});

test('fluxo completo em demonstração: executar, revisar o documento, ver o trecho na página e voltar ao histórico', async ({
  page,
}) => {
  const violacoes = vigiarCsp(page);

  await page.goto(`/#token=${TOKEN}`);
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('heading', { name: 'Nova execução' })).toBeVisible();
  await semViolacoesDeAcessibilidade(page);

  await page.getByLabel('Arquivos PDF').setInputFiles(PDFS);
  await page.getByRole('button', { name: 'Continuar' }).click();
  await expect(page.getByRole('radio', { name: /Demonstração/ })).toBeChecked();
  await semViolacoesDeAcessibilidade(page);
  await page.getByRole('button', { name: 'Executar' }).click();
  await expect(page.getByRole('heading', { name: /^Execução / })).toBeVisible();
  await expect(page.getByText('Concluída', { exact: true }).first()).toBeVisible({ timeout: 45_000 });
  const tabela = page.getByRole('table');
  await expect(tabela).toBeVisible();
  // c_replay/ guarda respostas reais do modelo: o aviso de extrações simuladas não pode aparecer
  await expect(page.getByText('Extrações simuladas')).toHaveCount(0);
  await semViolacoesDeAcessibilidade(page);

  const linhas = tabela.getByRole('row');
  await expect(linhas).toHaveCount(9); // cabeçalho + 8 documentos
  await expect(linhas.nth(1)).toContainText(/Revisão humana/);
  await expect(page.locator('.contador--sucesso')).toContainText('4'); // inclui o scan (07): o OCR gravado corrobora

  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: /relatório de exceções \(legível\)/i }).click();
  expect((await download).suggestedFilename()).toBe('relatorio_excecoes.md');

  await tabela.getByRole('link', { name: /^05_/ }).click();
  await expect(page.getByRole('heading', { name: /^05_/ })).toBeVisible();
  await expect(page.getByText(/DATAS_PAGAMENTO_ANTES_DA_COM/).first()).toBeVisible();

  await page.getByRole('button', { name: /Data de pagamento/ }).click();
  await expect(page.getByTestId('destaque-bbox')).toBeVisible();
  const imagem = page.getByRole('img', { name: /Página 1/ });
  await expect(imagem).toBeVisible();
  expect(await imagem.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await semViolacoesDeAcessibilidade(page);

  for (const aba of ['Validação', 'Conferência', 'Auditoria']) {
    await page.getByRole('tab', { name: new RegExp(aba) }).click();
    await semViolacoesDeAcessibilidade(page);
  }

  // decisão do operador: aprovar exige conferir cada motivo; a decisão fica ao lado do registro, que não muda
  const revisao = page.getByRole('region', { name: 'Decisão do operador' });
  await revisao.getByRole('radio', { name: 'Aprovado na revisão' }).check();
  for (const motivo of await revisao.getByRole('checkbox').all()) await motivo.check();
  await revisao.getByLabel('Quem está revisando').fill('Operadora E2E');
  await revisao.getByLabel(/Justificativa/).fill('Datas conferidas contra o aviso original.');
  await semViolacoesDeAcessibilidade(page);
  await revisao.getByRole('button', { name: 'Registrar decisão' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Registrar' }).click();
  await expect(revisao.getByText('Operadora E2E')).toBeVisible();
  await expect(page.getByText('Revisão humana', { exact: true }).first()).toBeVisible();
  await semViolacoesDeAcessibilidade(page);

  // o histórico lista a execução e a trilha leva de volta a ele
  await page
    .getByRole('navigation', { name: 'Você está em' })
    .getByRole('link', { name: 'Histórico' })
    .click();
  await expect(page.getByRole('heading', { name: 'Histórico', level: 1 })).toBeVisible();
  await expect(page.getByRole('link', { name: /8 documento\(s\)/ }).first()).toBeVisible();
  await semViolacoesDeAcessibilidade(page);

  expect(violacoes).toEqual([]);
});

test('tema escuro e texto muito grande: sem violações de acessibilidade e sem rolagem horizontal da página', async ({
  page,
}) => {
  await page.goto(`/#token=${TOKEN}`);
  await page.getByRole('button', { name: 'Aparência' }).click();
  const dialogo = page.getByRole('dialog', { name: 'Aparência' });
  await dialogo.getByRole('radio', { name: /escuro/i }).check();
  await dialogo.getByRole('radio', { name: /muito grande/i }).check();
  await expect(page.locator('html')).toHaveAttribute('data-tema', 'escuro');
  await semViolacoesDeAcessibilidade(page); // com o diálogo aberto
  await page.keyboard.press('Escape');
  await expect(dialogo).toBeHidden();

  await semViolacoesDeAcessibilidade(page);
  const estouro = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(estouro).toBeLessThanOrEqual(0);

  await page.reload(); // a escolha sobrevive ao recarregamento
  await expect(page.locator('html')).toHaveAttribute('data-texto', 'maior');
});

test('dá para usar tudo só com o teclado, com foco sempre visível', async ({ page }) => {
  await page.goto(`/#token=${TOKEN}`);
  await expect(page.getByRole('heading', { name: 'Nova execução' })).toBeVisible();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Pular para o conteúdo' })).toBeFocused();
  // percorre a página inteira com Tab: todo foco tem anel visível e o foco nunca fica preso
  const vistos = new Set<string>();
  for (let i = 0; i < 60; i += 1) {
    await page.keyboard.press('Tab');
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const estilo = getComputedStyle(el);
      return {
        id: `${el.tagName}:${el.textContent.trim().slice(0, 30)}:${el.getAttribute('name') ?? ''}:${el.getAttribute('value') ?? ''}`,
        anel: estilo.outlineStyle !== 'none' && parseFloat(estilo.outlineWidth) > 0,
        visivel: el.getBoundingClientRect().height > 0,
      };
    });
    if (info === null) break; // saiu da página (volta ao navegador): percorreu tudo
    expect(info.visivel).toBe(true);
    expect(info.anel, `sem anel de foco em ${info.id}`).toBe(true);
    vistos.add(info.id);
  }
  const ids = [...vistos];
  expect(ids.some((id) => id.startsWith('INPUT:'))).toBe(true); // o campo de arquivos
  expect(ids.some((id) => id.startsWith('BUTTON:Continuar'))).toBe(true);

  // o menu e as abas respondem ao teclado
  await page.getByRole('link', { name: 'Histórico' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Histórico', exact: true })).toBeVisible();
});

test('o escaneado não ganha destaque inventado', async ({ page }) => {
  await page.goto(`/#token=${TOKEN}`);
  await page
    .getByRole('link', { name: /Execuções recentes|\d+ documento/ })
    .first()
    .click();
  await page.getByRole('link', { name: /^07_/ }).click();
  await page.getByRole('button', { name: /Data de pagamento/ }).click();
  await expect(page.getByRole('status').filter({ hasText: /sem posição na página/ })).toBeVisible();
  await expect(page.getByTestId('destaque-bbox')).toHaveCount(0);
});

test('API recusa Host inesperado (DNS rebinding)', async ({ request }) => {
  const resposta = await request.get('/api/saude', {
    headers: { Authorization: `Bearer ${TOKEN}`, Host: 'evil.example.com' },
  });
  expect(resposta.status()).toBe(400);
});
