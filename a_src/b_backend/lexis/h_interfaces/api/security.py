"""Controles de segurança da API local.

Modelo de ameaça: a API roda na máquina do operador e executa código Python (que lê PDFs não confiáveis e pode gastar
dinheiro com o modelo). Qualquer página aberta no navegador consegue enviar requisições para `localhost`, e DNS
rebinding permite apontar um nome externo para 127.0.0.1. Por isso:
  1. só escuta em loopback (garantido em `cli.py`). Exceção: dentro de um container (`serve --container`) escuta em
     0.0.0.0 da rede do container, e quem publica a porta só em 127.0.0.1 do host é o `docker-compose.yml`;
  2. exige token aleatório por subida (Bearer; não usa cookie, logo não há CSRF), conferido ANTES de ler o corpo;
  3. confere o cabeçalho Host (anti DNS rebinding);
  4. recusa uploads antes de ler o corpo se o Content-Length estoura o limite;
  5. aplica cabeçalhos de segurança (CSP restritiva, sem cache, sem sniffing).
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import Request
from starlette.responses import JSONResponse, Response

HOSTS_PERMITIDOS = frozenset({"127.0.0.1", "localhost", "[::1]"})
HOST_DO_CONTAINER = "0.0.0.0"  # noqa: S104 (só com --container; ver em_container)
# Marcadores criados pelo Docker e pelo Podman na raiz do container
MARCADORES_DE_CONTAINER = (Path("/.dockerenv"), Path("/run/.containerenv"))

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
    "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
CABECALHOS_BASE = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def gerar_token() -> str:
    return secrets.token_urlsafe(32)


def hostname(valor_do_host: str) -> str:
    """`127.0.0.1:8000` -> `127.0.0.1`; `[::1]:8000` -> `[::1]`."""
    v = valor_do_host.strip().lower()
    if v.startswith("["):
        return v.split("]", 1)[0] + "]"
    return v.rsplit(":", 1)[0] if ":" in v else v


def host_permitido(valor_do_host: str | None) -> bool:
    return bool(valor_do_host) and hostname(valor_do_host or "") in HOSTS_PERMITIDOS


def em_container(marcadores: tuple[Path, ...] = MARCADORES_DE_CONTAINER) -> bool:
    """`--container` só vale dentro de um container: fora dele, escutar em 0.0.0.0 exporia a API à rede."""
    return any(m.exists() for m in marcadores)


def token_valido(recebido: str | None, esperado: str) -> bool:
    return recebido is not None and secrets.compare_digest(recebido.encode(), esperado.encode())


def extrair_bearer(cabecalho: str | None) -> str | None:
    if not cabecalho:
        return None
    partes = cabecalho.split(" ", 1)
    return partes[1].strip() if len(partes) == 2 and partes[0].lower() == "bearer" else None


def middleware_de_protecao(
    token: str, max_upload_bytes: int,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Ordem importa: Host -> token -> limite de upload -> rota. Tudo antes de ler qualquer corpo."""

    async def protecao(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        caminho = request.url.path
        recusa: Response | None = None
        if not host_permitido(request.headers.get("host")):
            recusa = JSONResponse({"detail": "host não permitido"}, status_code=400)
        elif caminho.startswith("/api/") and not token_valido(extrair_bearer(request.headers.get("authorization")),
                                                              token):
            recusa = JSONResponse({"detail": "token ausente ou inválido"}, status_code=401,
                                  headers={"WWW-Authenticate": "Bearer"})
        elif request.method == "POST" and caminho == "/api/uploads" and _corpo_grande_demais(request,
                                                                                            max_upload_bytes):
            recusa = JSONResponse({"detail": "envio acima do limite"}, status_code=413)
        resposta = recusa if recusa is not None else await call_next(request)
        for chave, valor in CABECALHOS_BASE.items():
            resposta.headers[chave] = valor
        if caminho.startswith("/api/"):
            resposta.headers["Cache-Control"] = "no-store"
        return resposta

    return protecao


def _corpo_grande_demais(request: Request, limite: int) -> bool:
    bruto = request.headers.get("content-length")
    if bruto is None or not bruto.isdigit():
        return True  # sem Content-Length confiável não dá para limitar antes de ler: recusa
    return int(bruto) > limite
