import { useEffect, useId, useRef, useState, useSyncExternalStore } from 'react';
import {
  assinarPreferencias,
  definirPreferencias,
  obterPreferencias,
  restaurarPreferencias,
  type TamanhoTexto,
  type Tema,
} from '../preferences/preferences';
import { Icone, type NomeIcone } from './Icon';

const OPCOES_TEMA: { valor: Tema; rotulo: string; descricao: string; icone: NomeIcone }[] = [
  {
    valor: 'sistema',
    rotulo: 'Seguir o sistema',
    descricao: 'Usa o tema do seu computador',
    icone: 'monitor',
  },
  { valor: 'claro', rotulo: 'Claro', descricao: 'Fundo branco', icone: 'sol' },
  { valor: 'escuro', rotulo: 'Escuro', descricao: 'Fundo escuro, menos brilho', icone: 'lua' },
];

const OPCOES_TEXTO: { valor: TamanhoTexto; rotulo: string }[] = [
  { valor: 'pequeno', rotulo: 'Pequeno' },
  { valor: 'padrao', rotulo: 'Padrão' },
  { valor: 'grande', rotulo: 'Grande' },
  { valor: 'maior', rotulo: 'Muito grande' },
];

/** Botão que abre o painel de aparência: tema e tamanho do texto, com efeito imediato. Usa o <dialog> nativo. */
export function Aparencia({ className = '' }: { className?: string }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [aberto, setAberto] = useState(false);
  const idTitulo = useId();
  const prefs = useSyncExternalStore(assinarPreferencias, obterPreferencias);

  useEffect(() => {
    const dialogo = ref.current;
    if (!dialogo) return;
    if (aberto && !dialogo.open) dialogo.showModal();
    if (!aberto && dialogo.open) dialogo.close();
  }, [aberto]);

  return (
    <>
      <button
        type="button"
        className={`botao botao--fantasma ${className}`.trim()}
        aria-haspopup="dialog"
        onClick={() => {
          setAberto(true);
        }}
      >
        <Icone nome="ajustes" />
        Aparência
      </button>
      <dialog
        ref={ref}
        className="dialogo"
        aria-labelledby={idTitulo}
        onCancel={(evento) => {
          evento.preventDefault();
          setAberto(false);
        }}
        onClose={() => {
          setAberto(false);
        }}
      >
        <h2 id={idTitulo} className="dialogo__titulo">
          <Icone nome="ajustes" tamanho={22} />
          Aparência
        </h2>

        <fieldset className="grupo-opcoes">
          <legend>Tema</legend>
          <div className="opcoes-cartao opcoes-cartao--coluna">
            {OPCOES_TEMA.map((o) => (
              <label key={o.valor} className="opcao-cartao">
                <input
                  type="radio"
                  name="tema"
                  value={o.valor}
                  checked={prefs.tema === o.valor}
                  onChange={() => {
                    definirPreferencias({ tema: o.valor });
                  }}
                />
                <Icone nome={o.icone} tamanho={18} className="opcao-cartao__icone" />
                <span className="opcao-cartao__texto">
                  <strong>{o.rotulo}</strong> <span className="nota">{o.descricao}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset className="grupo-opcoes">
          <legend>Tamanho do texto</legend>
          <div className="opcoes-cartao opcoes-cartao--quatro">
            {OPCOES_TEXTO.map((o) => (
              <label key={o.valor} className="opcao-cartao opcao-cartao--centro">
                <input
                  type="radio"
                  name="tamanho-texto"
                  value={o.valor}
                  checked={prefs.texto === o.valor}
                  onChange={() => {
                    definirPreferencias({ texto: o.valor });
                  }}
                />
                <span className="opcao-cartao__texto">{o.rotulo}</span>
              </label>
            ))}
          </div>
          <p className="amostra-texto">
            Exemplo: <strong>Data de pagamento</strong> 10/07/2026 · Revisão humana
          </p>
        </fieldset>

        <p className="nota">
          Suas escolhas ficam salvas neste navegador. O tamanho padrão respeita a fonte configurada no
          navegador.
        </p>

        <div className="dialogo__acoes">
          <button type="button" className="botao botao--secundario" onClick={restaurarPreferencias}>
            Restaurar padrão
          </button>
          <button
            type="button"
            className="botao"
            onClick={() => {
              setAberto(false);
            }}
          >
            Concluir
          </button>
        </div>
      </dialog>
    </>
  );
}
