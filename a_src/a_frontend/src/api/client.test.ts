import { describe, expect, it } from 'vitest';
import { api, ErroApi } from './client';
import { definirToken } from '../auth/token';
import { corpoJson, json, simularApi, urlDe } from '../test/util';

describe('cliente da API', () => {
  it('envia o token no cabeçalho Authorization e nunca na URL', async () => {
    definirToken('segredo-123');
    const mock = simularApi({});
    await api.saude();
    const [url, init] = mock.mock.calls[0] ?? [];
    expect(urlDe(url ?? '')).toBe('/api/saude');
    expect(urlDe(url ?? '')).not.toContain('segredo');
    expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer segredo-123');
    expect(init?.credentials).toBe('same-origin'); // o cookie de sessão só vai para a própria origem
    expect(init?.cache).toBe('no-store');
  });

  it('não envia Authorization quando não há token', async () => {
    const mock = simularApi({});
    await api.saude();
    const init = mock.mock.calls[0]?.[1];
    expect((init?.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('transforma erro HTTP em ErroApi com a mensagem do servidor', async () => {
    simularApi({ 'GET /api/saude': () => json({ detail: 'token inválido' }, 401) });
    const falha = await api.saude().catch((e: unknown) => e);
    expect(falha).toBeInstanceOf(ErroApi);
    expect((falha as ErroApi).status).toBe(401);
    expect((falha as ErroApi).message).toBe('token inválido');
  });

  it('usa mensagem genérica quando o corpo do erro não é JSON', async () => {
    simularApi({ 'GET /api/saude': () => new Response('<html>', { status: 502 }) });
    await expect(api.saude()).rejects.toMatchObject({ status: 502, message: 'Erro 502' });
  });

  it('codifica nomes de documento na URL (sem montar caminho com texto cru)', async () => {
    const mock = simularApi({});
    await api.documento('abc123abc123', '../../etc passwd.pdf').catch(() => undefined);
    expect(urlDe(mock.mock.calls[0]?.[0] ?? '')).toBe(
      '/api/execucoes/abc123abc123/documentos/..%2F..%2Fetc%20passwd.pdf',
    );
  });

  it('envia PDFs como multipart no campo "arquivos"', async () => {
    const mock = simularApi({ 'POST /api/uploads': () => json({ id: 'a'.repeat(12), arquivos: [] }) });
    const arquivo = new File(['%PDF-1.4'], 'aviso.pdf', { type: 'application/pdf' });
    await api.enviar([arquivo]);
    const corpo = mock.mock.calls[0]?.[1]?.body;
    expect(corpo).toBeInstanceOf(FormData);
    expect((corpo as FormData).getAll('arquivos')).toHaveLength(1);
  });

  it('envia o pedido de execução como JSON', async () => {
    const mock = simularApi({ 'POST /api/execucoes': () => json({}, 200) });
    await api.iniciarExecucao({ origem: 'amostras', modo: 'replay', sem_ocr: false, confirmar_live: false });
    const init = mock.mock.calls[0]?.[1];
    expect(init?.method).toBe('POST');
    expect(corpoJson(init)).toMatchObject({ origem: 'amostras', modo: 'replay' });
  });
});
