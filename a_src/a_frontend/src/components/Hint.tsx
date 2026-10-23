import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Icone } from './Icon';

const MARGEM = 8; // distância mínima da borda da janela e do gatilho, em px

/**
 * Explicação sob demanda (toggletip): um botão "?" abre um popover com o conceito, sem ocupar espaço na tela.
 *
 * Usa a Popover API nativa: camada superior (escapa de tabelas roláveis e cartões), fecha com Esc ou clique fora,
 * o foco volta ao gatilho e o navegador expõe o estado aberto/fechado. Abre no clique, não no hover, para
 * funcionar no toque e no teclado. A posição é aplicada via CSSOM (element.style), compatível com a CSP.
 */
export function Dica({ rotulo, titulo, children }: { rotulo: string; titulo?: string; children: ReactNode }) {
  const id = useId();
  const gatilho = useRef<HTMLButtonElement>(null);
  const painel = useRef<HTMLDivElement>(null);
  const [aberta, setAberta] = useState(false);

  const posicionar = useCallback(() => {
    const g = gatilho.current?.getBoundingClientRect();
    const p = painel.current;
    if (!g || !p) return;
    const { width, height } = p.getBoundingClientRect();
    const larguraJanela = document.documentElement.clientWidth;
    const cabeAbaixo = g.bottom + MARGEM + height <= window.innerHeight - MARGEM;
    const topo = cabeAbaixo || g.top - MARGEM - height < MARGEM ? g.bottom + MARGEM : g.top - MARGEM - height;
    const esquerda = Math.min(
      Math.max(MARGEM, g.left + g.width / 2 - width / 2),
      larguraJanela - width - MARGEM,
    );
    p.style.top = `${String(Math.round(topo))}px`;
    p.style.left = `${String(Math.round(esquerda))}px`;
  }, []);

  useEffect(() => {
    if (!aberta) return;
    window.addEventListener('resize', posicionar);
    window.addEventListener('scroll', posicionar, true);
    return () => {
      window.removeEventListener('resize', posicionar);
      window.removeEventListener('scroll', posicionar, true);
    };
  }, [aberta, posicionar]);

  return (
    <>
      <button
        ref={gatilho}
        type="button"
        className="dica__gatilho"
        popoverTarget={id}
        aria-label={`Sobre: ${rotulo}`}
        title={`Sobre: ${rotulo}`}
      >
        <Icone nome="ajuda" tamanho={15} />
      </button>
      <div
        ref={painel}
        id={id}
        popover="auto"
        role="dialog"
        aria-label={titulo ?? rotulo}
        className="dica"
        onToggle={(e) => {
          const abrindo = e.newState === 'open';
          setAberta(abrindo);
          if (abrindo) posicionar();
        }}
      >
        {titulo ? <p className="dica__titulo">{titulo}</p> : null}
        <div className="dica__corpo">{children}</div>
      </div>
    </>
  );
}

/** Título com a Dica ao lado (fora do heading, para não poluir o nome acessível do título). */
export function ComDica({ children, dica }: { children: ReactNode; dica: ReactNode }) {
  return (
    <div className="com-dica">
      {children}
      {dica}
    </div>
  );
}
