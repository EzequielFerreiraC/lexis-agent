import { useEffect, useRef, type ReactNode } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useSair, useSessao } from '../api/hooks';
import { limparToken } from '../auth/token';
import logoClaro from '../img/lexis-logo-light.png';
import logoEscuro from '../img/lexis-logo-dark.png';
import { Aparencia } from './Appearance';
import { Icone, type NomeIcone } from './Icon';

export function useTituloDaPagina(titulo: string): void {
  useEffect(() => {
    document.title = `${titulo} · Lexis`;
  }, [titulo]);
}

function Marca() {
  return (
    <div className="marca">
      <p className="marca__texto">
        <img className="marca__logo marca__logo--claro" src={logoClaro} alt="Lexis" />
        <img className="marca__logo marca__logo--escuro" src={logoEscuro} alt="" aria-hidden="true" />
        <span className="marca__sub">Revisão de eventos corporativos</span>
      </p>
    </div>
  );
}

const ITENS_MENU: { para: string; rotulo: string; icone: NomeIcone; fim?: boolean }[] = [
  { para: '/', rotulo: 'Executar', icone: 'play', fim: true },
  { para: '/historico', rotulo: 'Histórico', icone: 'historico' },
  { para: '/configuracoes', rotulo: 'Configurações', icone: 'engrenagem' },
];

export function Layout(): ReactNode {
  const { pathname } = useLocation();
  const principal = useRef<HTMLElement>(null);
  const primeira = useRef(true);
  const usuario = useSessao().data?.usuario ?? null;
  const sair = useSair();

  useEffect(() => {
    if (primeira.current) {
      primeira.current = false;
      return;
    }
    principal.current?.focus(); // quem usa teclado ou leitor de tela começa o conteúdo novo do início
  }, [pathname]);

  return (
    <div className="app">
      <a className="pular-para-conteudo" href="#conteudo">
        Pular para o conteúdo
      </a>
      <header className="topo">
        <div className="topo__miolo">
          <Marca />
          <nav className="topo__nav" aria-label="Principal">
            {ITENS_MENU.map((item) => (
              <NavLink key={item.para} className="topo__link" to={item.para} end={item.fim ?? false}>
                <Icone nome={item.icone} tamanho={18} />
                {item.rotulo}
              </NavLink>
            ))}
          </nav>
          <div className="topo__acoes">
            <Aparencia />
            {usuario ? (
              <span className="topo__usuario" title={`E-mail: ${usuario.login}`}>
                {usuario.nome}
              </span>
            ) : null}
            <button
              type="button"
              className="botao botao--fantasma"
              disabled={sair.isPending}
              onClick={() => {
                // com login, encerra a sessão no servidor; sem login, esquece o token desta aba
                if (usuario) sair.mutate(undefined);
                else limparToken();
              }}
            >
              <Icone nome="sair" />
              Sair
            </button>
          </div>
        </div>
      </header>
      <main id="conteudo" className="conteudo" ref={principal} tabIndex={-1}>
        <div className="conteudo__miolo">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
