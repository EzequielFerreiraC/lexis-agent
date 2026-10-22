"""Usuários e sessões do console, no banco.

- Senha: scrypt (biblioteca padrão, memória alta: caro de atacar por força bruta), sal aleatório por usuário; o banco
  guarda só `scrypt$N$r$p$sal$hash`. Comparação em tempo constante, e login inexistente também paga um scrypt (o
  tempo de resposta não revela quais logins existem).
- Sessão: token aleatório de 256 bits que só existe no cookie; o banco guarda o SHA-256 dele, então um vazamento da
  tabela não dá sessões válidas. Expira em `DURACAO_SESSAO`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Engine, delete, insert, select
from sqlalchemy.exc import IntegrityError

from lexis.g_adapters.sql_schema import sessao, usuario
from lexis.g_adapters.sql_store import agora_utc

N, R, P = 2**15, 8, 1  # ~32 MiB por verificação
MIN_SENHA, MAX_SENHA = 12, 200
DURACAO_SESSAO = timedelta(hours=8)
# e-mail pragmático: sem aspas nem IP literal; o domínio precisa de ao menos um ponto
EMAIL_RE = re.compile(r"[a-z0-9._%+-]{1,64}@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+")
MAX_EMAIL = 254
_SAL_FICTICIO = secrets.token_bytes(16)


class LoginEmUso(ValueError):
    """O e-mail pedido já pertence a outra conta."""


@dataclass(frozen=True)
class Usuario:
    id: int
    login: str
    nome: str


def _derivar(senha: str, sal: bytes, n: int = N, r: int = R, p: int = P) -> bytes:
    return hashlib.scrypt(senha.encode("utf-8"), salt=sal, n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=32)


def hash_senha(senha: str) -> str:
    sal = secrets.token_bytes(16)
    b64 = base64.b64encode
    return f"scrypt${N}${R}${P}${b64(sal).decode()}${b64(_derivar(senha, sal)).decode()}"


def senha_confere(senha: str, armazenado: str) -> bool:
    try:
        esquema, n, r, p, sal, esperado = armazenado.split("$")
        if esquema != "scrypt":
            return False
        obtido = _derivar(senha, base64.b64decode(sal), int(n), int(r), int(p))
        return hmac.compare_digest(obtido, base64.b64decode(esperado))
    except ValueError:
        return False


def normalizar_email(email: str) -> str:
    return email.strip().lower()


def dominio(email: str) -> str:
    return email.rpartition("@")[2]


def validar_senha(senha: str, email: str) -> None:
    if len(senha) < MIN_SENHA:
        raise ValueError(f"a senha precisa de ao menos {MIN_SENHA} caracteres")
    if len(senha) > MAX_SENHA:
        raise ValueError(f"a senha pode ter no máximo {MAX_SENHA} caracteres")
    usuario_do_email = email.partition("@")[0].lower()
    if len(usuario_do_email) >= 3 and usuario_do_email in senha.lower():
        raise ValueError("a senha não pode conter o seu e-mail")


def criar_usuario(engine: Engine, login: str, nome: str, senha: str) -> Usuario:
    login = normalizar_email(login)
    nome = " ".join(nome.split())
    if len(login) > MAX_EMAIL or not EMAIL_RE.fullmatch(login):
        raise ValueError("e-mail inválido")
    if not 2 <= len(nome) <= 80:
        raise ValueError("apelido: 2 a 80 caracteres")
    validar_senha(senha, login)
    with engine.begin() as con:
        if con.execute(select(usuario.c.id).where(usuario.c.login == login)).first():
            raise LoginEmUso("esse e-mail já tem uma conta")
    try:
        with engine.begin() as con:
            pk = con.execute(insert(usuario).values(
                login=login, nome=nome, senha_hash=hash_senha(senha), ativo=True, criado_em=agora_utc())
            ).inserted_primary_key
    except IntegrityError as e:  # outro cadastro com o mesmo login entrou entre a consulta e o insert
        raise LoginEmUso("esse e-mail já tem uma conta") from e
    assert pk is not None
    return Usuario(int(pk[0]), login, nome)


def autenticar(engine: Engine, login: str, senha: str) -> Usuario | None:
    with engine.connect() as con:
        linha = con.execute(select(usuario.c.id, usuario.c.login, usuario.c.nome, usuario.c.senha_hash)
                            .where(usuario.c.login == normalizar_email(login), usuario.c.ativo.is_(True))).first()
    if linha is None:
        _derivar(senha, _SAL_FICTICIO)  # mesmo custo de um login existente
        return None
    return Usuario(int(linha.id), linha.login, linha.nome) if senha_confere(senha, linha.senha_hash) else None


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def abrir_sessao(engine: Engine, u: Usuario) -> str:
    token = secrets.token_urlsafe(32)
    instante = agora_utc()
    with engine.begin() as con:
        con.execute(delete(sessao).where(sessao.c.expira_em < instante))  # limpeza oportunista
        con.execute(insert(sessao).values(token_sha256=_sha(token), usuario_id=u.id, criada_em=instante,
                                          expira_em=instante + DURACAO_SESSAO))
    return token


def usuario_da_sessao(engine: Engine, token: str | None) -> Usuario | None:
    if not token or len(token) > 100:
        return None
    with engine.connect() as con:
        linha = con.execute(
            select(usuario.c.id, usuario.c.login, usuario.c.nome)
            .join(sessao, sessao.c.usuario_id == usuario.c.id)
            .where(sessao.c.token_sha256 == _sha(token), sessao.c.expira_em > agora_utc(),
                   usuario.c.ativo.is_(True))).first()
    return Usuario(int(linha.id), linha.login, linha.nome) if linha else None


def encerrar_sessao(engine: Engine, token: str | None) -> None:
    if token:
        with engine.begin() as con:
            con.execute(delete(sessao).where(sessao.c.token_sha256 == _sha(token)))
