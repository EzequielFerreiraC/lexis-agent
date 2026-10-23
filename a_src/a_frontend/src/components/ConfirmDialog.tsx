import { useEffect, useId, useRef, type ReactNode } from 'react';
import { Icone } from './Icon';

/** Usa o <dialog> nativo: foco preso, Esc e fundo inerte vêm do navegador (sem CSS/JS injetado, compatível com a CSP). */
export function DialogoConfirmacao({
  aberto,
  titulo,
  children,
  rotuloConfirmar,
  perigo = false,
  aoConfirmar,
  aoCancelar,
}: {
  aberto: boolean;
  titulo: string;
  children: ReactNode;
  rotuloConfirmar: string;
  perigo?: boolean;
  aoConfirmar: () => void;
  aoCancelar: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const idTitulo = useId();

  useEffect(() => {
    const dialogo = ref.current;
    if (!dialogo) return;
    if (aberto && !dialogo.open) dialogo.showModal();
    if (!aberto && dialogo.open) dialogo.close();
  }, [aberto]);

  return (
    <dialog
      ref={ref}
      className="dialogo"
      aria-labelledby={idTitulo}
      onCancel={(evento) => {
        evento.preventDefault();
        aoCancelar();
      }}
    >
      <h2 id={idTitulo} className="dialogo__titulo">
        <Icone nome={perigo ? 'alerta' : 'info'} tamanho={22} />
        {titulo}
      </h2>
      {children}
      <div className="dialogo__acoes">
        <button type="button" className="botao botao--secundario" onClick={aoCancelar}>
          Cancelar
        </button>
        <button type="button" className={perigo ? 'botao botao--perigo' : 'botao'} onClick={aoConfirmar}>
          {rotuloConfirmar}
        </button>
      </div>
    </dialog>
  );
}
