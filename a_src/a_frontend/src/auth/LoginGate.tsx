import { useId, useState, type SyntheticEvent } from 'react';
import { useCadastrar, useEntrar, useSessao } from '../api/hooks';
import { Aparencia } from '../components/Appearance';
import { Icone } from '../components/Icon';
import { CaixaErro, Carregando } from '../components/States';

const MIN_SENHA = 12; // o servidor confere de novo; aqui é só para avisar antes de enviar

type Modo = 'entrar' | 'cadastrar';

/**
 * Depois do token (que só prova que é este servidor), o login diz QUEM está usando: com banco configurado, o
 * servidor exige uma sessão e a revisão humana passa a registrar o usuário autenticado. Sem banco, segue direto.
 */
export function PortaDeLogin({ children }: { children: React.ReactNode }) {
  const sessao = useSessao();
  const [modo, setModo] = useState<Modo>('entrar');

  if (sessao.isPending) return <Carregando />;
  if (sessao.isError) {
    return (
      <main className="acesso">
        <CaixaErro erro={sessao.error} aoTentarNovamente={() => void sessao.refetch()} />
      </main>
    );
  }
  if (!sessao.data.login_exigido || sessao.data.usuario) return <>{children}</>;
  const dominios = sessao.data.dominios_email;

  return (
    <main className="acesso">
      <div className="acesso__aparencia">
        <Aparencia />
      </div>
      <div className="acesso__cartao">
        <span className="acesso__icone" aria-hidden="true">
          <Icone nome="cadeado" tamanho={24} />
        </span>
        {modo === 'entrar' ? (
          <FormularioEntrar
            aoCriarConta={() => {
              setModo('cadastrar');
            }}
          />
        ) : (
          <FormularioCadastro
            dominios={dominios}
            aoEntrar={() => {
              setModo('entrar');
            }}
          />
        )}
      </div>
    </main>
  );
}

function FormularioEntrar({ aoCriarConta }: { aoCriarConta: () => void }) {
  const entrar = useEntrar();
  const idEmail = useId();
  const idSenha = useId();
  const [login, setLogin] = useState('');
  const [senha, setSenha] = useState('');

  const enviar = (evento: SyntheticEvent) => {
    evento.preventDefault();
    if (!login.trim() || !senha) return;
    entrar.mutate(
      { login: login.trim(), senha },
      {
        onSettled: () => {
          setSenha(''); // a senha não fica na tela nem no estado depois de enviada
        },
      },
    );
  };

  return (
    <>
      <h1>Entrar</h1>
      <p className="acesso__intro">Acesse o console com seu e-mail e senha.</p>
      <form onSubmit={enviar} noValidate>
        <CampoEmail id={idEmail} valor={login} aoMudar={setLogin} />
        <div className="campo-bloco">
          <label className="rotulo" htmlFor={idSenha}>
            Senha
          </label>
          <input
            id={idSenha}
            className="campo-texto"
            type="password"
            autoComplete="current-password"
            maxLength={200}
            value={senha}
            onChange={(e) => {
              setSenha(e.target.value);
            }}
          />
        </div>
        {entrar.isError ? <CaixaErro titulo="Não foi possível entrar" erro={entrar.error} /> : null}
        <button
          type="submit"
          className="botao botao--grande botao--bloco"
          disabled={entrar.isPending || !login.trim() || !senha}
        >
          {entrar.isPending ? 'Entrando…' : 'Entrar'}
        </button>
      </form>
      <p className="acesso__alternar">
        Não tem conta?{' '}
        <button type="button" className="botao botao--texto botao--pequeno" onClick={aoCriarConta}>
          Criar conta
        </button>
      </p>
    </>
  );
}

function FormularioCadastro({ dominios, aoEntrar }: { dominios: string[]; aoEntrar: () => void }) {
  const cadastrar = useCadastrar();
  const idNome = useId();
  const idNotaNome = useId();
  const idEmail = useId();
  const idSenha = useId();
  const idConfirma = useId();
  const idNotaSenha = useId();
  const idNotaConfirma = useId();
  const [nome, setNome] = useState('');
  const [login, setLogin] = useState('');
  const [senha, setSenha] = useState('');
  const [confirma, setConfirma] = useState('');

  const senhaCurta = senha.length > 0 && senha.length < MIN_SENHA;
  const naoConfere = confirma.length > 0 && confirma !== senha;
  const dominioRecusado = foraDosDominios(login, dominios);
  const pronto =
    nome.trim().length >= 2 &&
    login.includes('@') &&
    !dominioRecusado &&
    senha.length >= MIN_SENHA &&
    confirma === senha;

  const enviar = (evento: SyntheticEvent) => {
    evento.preventDefault();
    if (!pronto) return;
    cadastrar.mutate(
      { nome: nome.trim(), login: login.trim(), senha },
      {
        onSettled: () => {
          setSenha('');
          setConfirma('');
        },
      },
    );
  };

  return (
    <>
      <h1>Criar conta</h1>
      <p className="acesso__intro">Preencha seus dados para criar o acesso ao console.</p>
      <form onSubmit={enviar} noValidate>
        <div className="campo-bloco">
          <label className="rotulo" htmlFor={idNome}>
            Apelido
          </label>
          <input
            id={idNome}
            className="campo-texto"
            type="text"
            autoComplete="nickname"
            maxLength={80}
            aria-describedby={idNotaNome}
            value={nome}
            onChange={(e) => {
              setNome(e.target.value);
            }}
          />
          <p className="nota" id={idNotaNome}>
            Como você aparece no console e nas revisões que registrar.
          </p>
        </div>
        <CampoEmail
          id={idEmail}
          valor={login}
          aoMudar={setLogin}
          dominios={dominios}
          recusado={dominioRecusado}
          novo
        />
        <div className="campo-bloco">
          <label className="rotulo" htmlFor={idSenha}>
            Senha
          </label>
          <input
            id={idSenha}
            className="campo-texto"
            type="password"
            autoComplete="new-password"
            maxLength={200}
            aria-describedby={idNotaSenha}
            aria-invalid={senhaCurta || undefined}
            value={senha}
            onChange={(e) => {
              setSenha(e.target.value);
            }}
          />
          <p className="nota" id={idNotaSenha}>
            Mínimo de {MIN_SENHA} caracteres, sem conter o seu e-mail.
          </p>
        </div>
        <div className="campo-bloco">
          <label className="rotulo" htmlFor={idConfirma}>
            Confirmar senha
          </label>
          <input
            id={idConfirma}
            className="campo-texto"
            type="password"
            autoComplete="new-password"
            maxLength={200}
            aria-describedby={naoConfere ? idNotaConfirma : undefined}
            aria-invalid={naoConfere || undefined}
            value={confirma}
            onChange={(e) => {
              setConfirma(e.target.value);
            }}
          />
          {naoConfere ? (
            <p className="nota nota--erro" id={idNotaConfirma}>
              As senhas não conferem.
            </p>
          ) : null}
        </div>
        {cadastrar.isError ? (
          <CaixaErro titulo="Não foi possível criar a conta" erro={cadastrar.error} />
        ) : null}
        <button
          type="submit"
          className="botao botao--grande botao--bloco"
          disabled={cadastrar.isPending || !pronto}
        >
          {cadastrar.isPending ? 'Criando conta…' : 'Criar conta'}
        </button>
      </form>
      <p className="acesso__alternar">
        Já tem conta?{' '}
        <button type="button" className="botao botao--texto botao--pequeno" onClick={aoEntrar}>
          Entrar
        </button>
      </p>
    </>
  );
}

/** Com domínios configurados, avisa antes de enviar (o servidor confere de novo). */
function foraDosDominios(email: string, dominios: string[]): boolean {
  const arroba = email.lastIndexOf('@');
  if (!dominios.length || arroba < 0 || arroba === email.length - 1) return false;
  return !dominios.includes(
    email
      .slice(arroba + 1)
      .trim()
      .toLowerCase(),
  );
}

const listaDeDominios = (dominios: string[]) => dominios.map((d) => `@${d}`).join(' ou ');

function CampoEmail({
  id,
  valor,
  aoMudar,
  dominios = [],
  recusado = false,
  novo = false,
}: {
  id: string;
  valor: string;
  aoMudar: (valor: string) => void;
  dominios?: string[];
  recusado?: boolean;
  novo?: boolean;
}) {
  const idNota = useId();
  return (
    <div className="campo-bloco">
      <label className="rotulo" htmlFor={id}>
        E-mail
      </label>
      <input
        id={id}
        className="campo-texto"
        type="email"
        inputMode="email"
        autoComplete={novo ? 'email' : 'username'}
        autoCapitalize="off"
        spellCheck={false}
        maxLength={254}
        aria-describedby={novo ? idNota : undefined}
        aria-invalid={recusado || undefined}
        value={valor}
        onChange={(e) => {
          aoMudar(e.target.value);
        }}
      />
      {novo ? (
        <p className={recusado ? 'nota nota--erro' : 'nota'} id={idNota}>
          {recusado
            ? `Use um e-mail ${listaDeDominios(dominios)}.`
            : dominios.length
              ? `Usado para entrar. Use seu e-mail ${listaDeDominios(dominios)}.`
              : 'Usado para entrar.'}
        </p>
      ) : null}
    </div>
  );
}
