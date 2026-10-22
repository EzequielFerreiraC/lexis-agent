import { useSyncExternalStore, useState, type SyntheticEvent } from 'react';
import { Aparencia } from '../components/Appearance';
import { Icone } from '../components/Icon';
import { assinarToken, definirToken, obterToken } from './token';

/** Sem token, nada da interface (nem as telas) é exibido: a API recusaria tudo de qualquer forma. */
export function PortaDeAcesso({ children }: { children: React.ReactNode }) {
  const token = useSyncExternalStore(assinarToken, obterToken);
  const [digitado, setDigitado] = useState('');

  if (token) return <>{children}</>;

  const enviar = (evento: SyntheticEvent) => {
    evento.preventDefault();
    if (digitado.trim()) definirToken(digitado);
  };

  return (
    <main className="acesso">
      <div className="acesso__aparencia">
        <Aparencia />
      </div>
      <div className="acesso__cartao">
        <span className="acesso__icone" aria-hidden="true">
          <Icone nome="cadeado" tamanho={24} />
        </span>
        <h1>Acesso ao console</h1>
        <p className="acesso__intro">
          Este console fala com uma API local que executa código e pode gerar custo. Por isso ela exige um
          token, gerado a cada vez que o servidor sobe.
        </p>
        <ol className="acesso__passos">
          <li>
            Rode <code>lexis serve</code> no terminal.
          </li>
          <li>
            Abra o endereço impresso (ele termina em <code>#token=…</code>) <strong>ou</strong> cole o token
            abaixo.
          </li>
        </ol>
        <form onSubmit={enviar}>
          <label className="rotulo" htmlFor="token">
            Token de acesso
          </label>
          <input
            id="token"
            className="campo-texto"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={digitado}
            onChange={(e) => {
              setDigitado(e.target.value);
            }}
          />
          <p className="nota">O token fica só nesta aba do navegador e nunca vai na barra de endereço.</p>
          <button type="submit" className="botao botao--grande botao--bloco" disabled={!digitado.trim()}>
            Entrar
          </button>
        </form>
      </div>
    </main>
  );
}
