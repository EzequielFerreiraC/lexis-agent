import { defineConfig, devices } from '@playwright/test';

const PORTA = 8766;
export const TOKEN = 'token-e2e-playwright-0123456789';

// Sobe o servidor real (`lexis serve`) com o front compilado e fala com ele como um usuário faria.
// Pré-requisito: `npm run build` e `lexis` no PATH (pip install -e ".[web]").
export default defineConfig({
  testDir: './e2e',
  outputDir: '../../g_test_results/playwright',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  use: { baseURL: `http://127.0.0.1:${String(PORTA)}`, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `lexis serve --porta ${String(PORTA)} --execucoes g_test_results/execucoes`,
    cwd: '../..',
    url: `http://127.0.0.1:${String(PORTA)}/`,
    env: { LEXIS_TOKEN: TOKEN },
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
