import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import { ErroApi } from './api/client';
import { iniciarToken, limparToken } from './auth/token';
import { iniciarPreferencias } from './preferences/preferences';
import './design/tokens.css';
import './design/global.css';
import './design/components.css';

// Token recusado (servidor reiniciado gera outro): volta para a tela de acesso em vez de ficar em erro.
// Sessão expirada (com login): volta para a tela de login, mantendo o token.
const clienteDeConsultas = new QueryClient({
  queryCache: new QueryCache({
    onError: (erro) => {
      if (!(erro instanceof ErroApi) || erro.status !== 401) return;
      if (erro.exige === 'sessao') void clienteDeConsultas.invalidateQueries({ queryKey: ['sessao'] });
      else limparToken();
    },
  }),
  defaultOptions: {
    queries: {
      retry: (tentativas, erro) => !(erro instanceof ErroApi) && tentativas < 2,
      refetchOnWindowFocus: false,
    },
  },
});

iniciarPreferencias();
iniciarToken();

const raiz = document.getElementById('raiz');
if (!raiz) throw new Error('Elemento #raiz ausente no index.html');

createRoot(raiz).render(
  <StrictMode>
    <QueryClientProvider client={clienteDeConsultas}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
