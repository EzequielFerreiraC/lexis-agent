import { Route, Routes } from 'react-router-dom';
import { PortaDeAcesso } from './auth/AccessGate';
import { PortaDeLogin } from './auth/LoginGate';
import { Layout } from './components/Layout';
import { ConfiguracoesPagina } from './pages/SettingsPage';
import { DocumentoPagina } from './pages/DocumentPage';
import { ExecucaoPagina } from './pages/RunPage';
import { HistoricoPagina } from './pages/HistoryPage';
import { ExecutarPagina } from './pages/NewRunPage';
import { NaoEncontrada } from './pages/NotFoundPage';

export function App() {
  return (
    <PortaDeAcesso>
      <PortaDeLogin>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<ExecutarPagina />} />
            <Route path="execucoes/:id" element={<ExecucaoPagina />} />
            <Route path="execucoes/:id/documentos/:nome" element={<DocumentoPagina />} />
            <Route path="historico" element={<HistoricoPagina />} />
            <Route path="configuracoes" element={<ConfiguracoesPagina />} />
            <Route path="*" element={<NaoEncontrada />} />
          </Route>
        </Routes>
      </PortaDeLogin>
    </PortaDeAcesso>
  );
}
