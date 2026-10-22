"""Aplicação FastAPI: a mesma lógica da CLI (`run`, `avaliar`) exposta em HTTP, só para uso local.

Sem `from __future__ import annotations` de propósito: o FastAPI resolve as anotações das rotas em tempo de execução.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

import lexis
from lexis.a_domain.models import RegistroSaida
from lexis.a_domain.specs import SPECS
from lexis.b_ingestion.pdf import MAX_BYTES
from lexis.h_interfaces.api.config import ConfigServidor
from lexis.h_interfaces.api.models import (
    Amostra,
    CadastroNovo,
    Catalogo,
    ChaveNova,
    Configuracao,
    Erro,
    ExecucaoNova,
    ExecucaoResumo,
    LoginNovo,
    PaginaExecucoes,
    PaginaMeta,
    RegraCatalogo,
    RevisaoHumana,
    RevisaoNova,
    Saude,
    SessaoInfo,
    TipoCatalogo,
    UploadResposta,
)
from lexis.h_interfaces.api.security import middleware_de_protecao
from lexis.h_interfaces.api.service import ErroDeUso, ServicoExecucoes

if TYPE_CHECKING:
    from lexis.g_adapters.sql_users import Usuario

# Cookie da sessão: HttpOnly (o JavaScript não lê), SameSite=Strict (outro site não o envia) e só em /api. O token
# Bearer por subida continua exigido em toda rota: CSRF precisaria dos dois.
COOKIE_SESSAO = "lexis_sessao"

TIPOS_DE_RELATORIO = {
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
}
NAO_ENCONTRADO: dict[int | str, dict[str, Any]] = {404: {"model": Erro}}


def _servico(request: Request) -> ServicoExecucoes:
    servico: ServicoExecucoes = request.app.state.servico
    return servico


def _usuario(request: Request) -> Optional["Usuario"]:
    """Com login exigido, toda rota da API (menos /api/sessao) precisa de uma sessão válida."""
    svc = _servico(request)
    if not svc.login_exigido:
        return None
    u = svc.usuario_da_sessao(request.cookies.get(COOKIE_SESSAO))
    if u is None:
        raise HTTPException(status_code=401, detail="sessão ausente ou expirada",
                            headers={"WWW-Authenticate": "Session"})
    return u


def criar_app(config: ConfigServidor, servico: ServicoExecucoes | None = None) -> FastAPI:
    svc_unico = servico or ServicoExecucoes(config)

    @asynccontextmanager
    async def ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
        yield
        svc_unico.encerrar()

    app = FastAPI(
        title="Lexis API", version=lexis.__version__, lifespan=ciclo_de_vida,
        docs_url=None, redoc_url=None, openapi_url=None,  # contrato exportado por script; sem documentação pública
    )
    app.state.servico = svc_unico
    # 20 arquivos de no máximo MAX_BYTES + folga para o multipart
    app.middleware("http")(middleware_de_protecao(config.token, config.max_arquivos * MAX_BYTES + 1_000_000))

    @app.exception_handler(ErroDeUso)
    async def erro_de_uso(_: Request, erro: ErroDeUso) -> JSONResponse:
        return JSONResponse({"detail": erro.detalhe}, status_code=erro.status)

    sessoes = APIRouter(prefix="/api")

    def _guardar_sessao(response: Response, token: str) -> None:
        response.set_cookie(COOKIE_SESSAO, token, httponly=True, samesite="strict", path="/api",
                            secure=config.cookie_seguro, max_age=8 * 3600)

    @sessoes.get("/sessao", response_model=SessaoInfo)
    def sessao(request: Request, svc: ServicoExecucoes = Depends(_servico)) -> SessaoInfo:
        """Se o console exige login e quem está logado (nunca o token da sessão)."""
        return svc.sessao(request.cookies.get(COOKIE_SESSAO))

    @sessoes.post("/sessao", response_model=SessaoInfo,
                  responses={401: {"model": Erro}, 404: {"model": Erro}, 429: {"model": Erro}})
    def entrar(req: LoginNovo, response: Response, svc: ServicoExecucoes = Depends(_servico)) -> SessaoInfo:
        info, token = svc.entrar(req)
        _guardar_sessao(response, token)
        return info

    @sessoes.post("/usuarios", response_model=SessaoInfo, status_code=201,
                  responses={400: {"model": Erro}, 404: {"model": Erro}, 409: {"model": Erro}})
    def cadastrar(req: CadastroNovo, response: Response, svc: ServicoExecucoes = Depends(_servico)) -> SessaoInfo:
        """Cria a conta e já entra com ela."""
        info, token = svc.cadastrar(req)
        _guardar_sessao(response, token)
        return info

    @sessoes.delete("/sessao", response_model=SessaoInfo)
    def sair(request: Request, response: Response, svc: ServicoExecucoes = Depends(_servico)) -> SessaoInfo:
        svc.sair(request.cookies.get(COOKIE_SESSAO))
        response.delete_cookie(COOKIE_SESSAO, path="/api", httponly=True, samesite="strict",
                               secure=config.cookie_seguro)
        return svc.sessao(None)

    api = APIRouter(prefix="/api", dependencies=[Depends(_usuario)])

    @api.get("/saude", response_model=Saude)
    def saude(svc: ServicoExecucoes = Depends(_servico)) -> Saude:
        return svc.saude()

    @api.get("/configuracao", response_model=Configuracao)
    def configuracao(svc: ServicoExecucoes = Depends(_servico)) -> Configuracao:
        """Modelo em uso (do ambiente) e estado da chave de API (nunca a chave)."""
        return svc.configuracao()

    @api.put("/configuracao/chave", response_model=Configuracao, responses={400: {"model": Erro}})
    def guardar_chave(req: ChaveNova, svc: ServicoExecucoes = Depends(_servico)) -> Configuracao:
        """Guarda a chave só na memória do servidor, até ele reiniciar."""
        return svc.definir_chave(req)

    @api.delete("/configuracao/chave", response_model=Configuracao)
    def remover_chave(svc: ServicoExecucoes = Depends(_servico)) -> Configuracao:
        return svc.remover_chave()

    @api.get("/catalogo", response_model=Catalogo)
    def catalogo() -> Catalogo:
        """Rótulos, regras e matriz de aplicabilidade: a mesma fonte de verdade (`rules.json`) que o pipeline usa."""
        return Catalogo(
            versao=SPECS.versao, campos=list(SPECS.campos), rotulos=SPECS.rotulos,
            regras={k: RegraCatalogo(**v) for k, v in SPECS.regras.items()},
            tipos={k: TipoCatalogo(rotulo=t["rotulo"], tratamento_tributario=t["tratamento_tributario"],
                                   criticos=t["criticos"], aplicabilidade=t["aplicabilidade"])
                   for k, t in SPECS.tipos.items()},
        )

    @api.get("/amostras", response_model=list[Amostra])
    def amostras(svc: ServicoExecucoes = Depends(_servico)) -> list[Amostra]:
        return svc.listar_amostras()

    @api.post("/uploads", response_model=UploadResposta, status_code=201,
              responses={413: {"model": Erro}, 415: {"model": Erro}})
    def enviar(arquivos: list[UploadFile], svc: ServicoExecucoes = Depends(_servico)) -> UploadResposta:
        itens: list[tuple[str, bytes]] = []
        for f in arquivos:
            dados = f.file.read(MAX_BYTES + 1)  # nunca lê além do limite
            itens.append((f.filename or "documento.pdf", dados))
        return svc.criar_upload(itens)

    @api.post("/execucoes", response_model=ExecucaoResumo, status_code=202, responses={400: {"model": Erro}})
    def iniciar(req: ExecucaoNova, svc: ServicoExecucoes = Depends(_servico)) -> ExecucaoResumo:
        return svc.iniciar_execucao(req)

    @api.get("/execucoes", response_model=PaginaExecucoes)
    def execucoes(
        limite: int = Query(20, ge=1, le=100, description="itens por página"),
        deslocamento: int = Query(0, ge=0, description="quantos itens pular (mais recentes primeiro)"),
        svc: ServicoExecucoes = Depends(_servico),
    ) -> PaginaExecucoes:
        return svc.listar_execucoes(limite, deslocamento)

    @api.get("/execucoes/{run_id}", response_model=ExecucaoResumo, responses=NAO_ENCONTRADO)
    def execucao(run_id: str, svc: ServicoExecucoes = Depends(_servico)) -> ExecucaoResumo:
        return svc.obter_execucao(run_id)

    @api.get("/execucoes/{run_id}/documentos/{nome}", response_model=RegistroSaida, responses=NAO_ENCONTRADO)
    def documento(run_id: str, nome: str, svc: ServicoExecucoes = Depends(_servico)) -> RegistroSaida:
        return svc.obter_registro(run_id, nome)

    @api.post("/execucoes/{run_id}/documentos/{nome}/revisao", response_model=RevisaoHumana, status_code=201,
              responses={400: {"model": Erro}, 404: {"model": Erro}, 409: {"model": Erro}})
    def revisar(run_id: str, nome: str, req: RevisaoNova, svc: ServicoExecucoes = Depends(_servico),
                usuario: Any = Depends(_usuario)) -> RevisaoHumana:  # Any: o FastAPI avalia a anotação em execução
        """Decisão do operador sobre um documento em revisão humana. O registro do pipeline não é alterado.
        Com login, o operador é o usuário da sessão."""
        return svc.revisar(run_id, nome, req, usuario)

    @api.get("/execucoes/{run_id}/documentos/{nome}/paginas/{numero}", response_model=PaginaMeta,
             responses=NAO_ENCONTRADO)
    def pagina(run_id: str, nome: str, numero: int, svc: ServicoExecucoes = Depends(_servico)) -> PaginaMeta:
        return svc.meta_pagina(run_id, nome, numero)

    @api.get("/execucoes/{run_id}/documentos/{nome}/paginas/{numero}/imagem", responses={
        200: {"content": {"image/png": {}}}, 404: {"model": Erro}})
    def imagem(run_id: str, nome: str, numero: int, svc: ServicoExecucoes = Depends(_servico)) -> Response:
        """Página renderizada no servidor. O navegador NUNCA recebe nem abre o PDF original (entrada não confiável)."""
        return Response(content=svc.imagem_pagina(run_id, nome, numero), media_type="image/png")

    @api.get("/execucoes/{run_id}/relatorios/{arquivo}", responses={200: {"content": {"application/octet-stream": {}}},
                                                                    404: {"model": Erro}})
    def relatorio(run_id: str, arquivo: str, svc: ServicoExecucoes = Depends(_servico)) -> FileResponse:
        caminho = svc.caminho_relatorio(run_id, arquivo)
        return FileResponse(caminho, media_type=TIPOS_DE_RELATORIO.get(caminho.suffix, "application/octet-stream"),
                            filename=arquivo)

    app.include_router(sessoes)
    app.include_router(api)

    @app.get("/{caminho:path}", include_in_schema=False)
    def front(caminho: str) -> Response:
        """Serve o front compilado. O caminho é resolvido DENTRO da pasta do build; o resto cai no index (SPA)."""
        if caminho == "api" or caminho.startswith("api/"):
            raise HTTPException(status_code=404, detail="não encontrado")
        raiz = config.dir_front.resolve()
        indice = raiz / "index.html"
        if not indice.is_file():
            return JSONResponse({"detail": "front-end não compilado: rode `npm run build` em a_src/a_frontend"},
                                status_code=503)
        alvo = (raiz / caminho).resolve()
        if caminho and alvo.is_file() and raiz in alvo.parents:
            cache = "public, max-age=31536000, immutable" if caminho.startswith("assets/") else "no-cache"
            return FileResponse(alvo, headers={"Cache-Control": cache})
        return FileResponse(indice, headers={"Cache-Control": "no-cache"})

    return app
