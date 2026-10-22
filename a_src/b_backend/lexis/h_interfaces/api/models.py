"""Contrato HTTP da API (modelos Pydantic). O OpenAPI gerado a partir daqui alimenta os tipos TypeScript do front."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

Modo = Literal["replay", "auto", "live"]
EstadoJob = Literal["NA_FILA", "EM_ANDAMENTO", "CONCLUIDA", "FALHOU"]


class Estrito(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModoInfo(Estrito):
    id: Modo
    disponivel: bool
    descricao: str
    motivo_indisponivel: str | None = None


class Limites(Estrito):
    max_bytes_por_arquivo: int
    max_arquivos: int


class Saude(Estrito):
    versao_pipeline: str
    versoes: dict[str, str]
    modelo: str
    modos: list[ModoInfo]
    ocr_disponivel: bool
    orcamento_tokens: int
    gravacoes_simuladas: bool
    limites: Limites


class ChaveInfo(Estrito):
    """Estado da chave de API. A chave em si nunca sai do servidor: só se existe, de onde veio e os 4 últimos caracteres."""

    configurada: bool
    origem: Literal["tela", "ambiente"] | None = Field(description="tela = digitada no console (só em memória)")
    final: str | None = None


class Configuracao(Estrito):
    """O modelo é configuração de deploy (LEXIS_MODEL), não escolha do operador: o console só o mostra."""

    provedor: str
    modelo: str
    preco_entrada_usd_mtok: float | None = Field(description="preço de lista por milhão de tokens; None = desconhecido")
    preco_saida_usd_mtok: float | None
    chave: ChaveInfo


class UsuarioInfo(Estrito):
    login: str
    nome: str


class SessaoInfo(Estrito):
    """Com banco configurado, o console exige login; sem banco, não há onde guardar usuários e o login não existe."""

    login_exigido: bool
    usuario: UsuarioInfo | None = None
    dominios_email: list[str] = Field(default=[], description="domínios aceitos no cadastro; vazio = qualquer um")


class LoginNovo(Estrito):
    # senha sem limite aqui (o serviço confere): o 422 padrão devolveria a senha digitada no corpo da resposta
    login: str = Field(max_length=254, description="e-mail")
    senha: SecretStr


class CadastroNovo(Estrito):
    # tamanho e força da senha são conferidos no serviço, como no LoginNovo
    login: str = Field(max_length=254, description="e-mail")
    nome: str = Field(max_length=80, description="apelido: como a pessoa aparece no console e nas revisões")
    senha: SecretStr


class ChaveNova(Estrito):
    # SecretStr: não aparece em repr nem em log. Tamanho e formato são conferidos no serviço, com mensagem fixa: um
    # limite aqui geraria o 422 padrão, que devolve a entrada no corpo da resposta.
    chave: SecretStr


class RegraCatalogo(Estrito):
    severidade: Literal["ERRO", "AVISO", "INFO"]
    descricao: str


class TipoCatalogo(Estrito):
    rotulo: str
    tratamento_tributario: str
    criticos: list[str]
    aplicabilidade: dict[str, str]


class Catalogo(Estrito):
    versao: str
    campos: list[str]
    rotulos: dict[str, str]
    regras: dict[str, RegraCatalogo]
    tipos: dict[str, TipoCatalogo]


class Amostra(Estrito):
    nome: str
    tamanho: int
    sha256: str


class ArquivoEnviado(Estrito):
    nome: str
    tamanho: int
    sha256: str


class UploadResposta(Estrito):
    id: str
    arquivos: list[ArquivoEnviado]


class ExecucaoNova(Estrito):
    origem: Literal["amostras", "upload"]
    arquivos: list[str] | None = Field(default=None, max_length=50, description="nomes; omitido = todos")
    upload_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{12}$")
    modo: Modo = "replay"
    sem_ocr: bool = False
    confirmar_live: bool = Field(default=False, description="obrigatório no modo live (gera custo)")


DecisaoHumana = Literal["APROVADO_NA_REVISAO", "REJEITADO_NA_REVISAO"]


class RevisaoNova(Estrito):
    """Decisão do operador sobre um documento em REVISAO_HUMANA. Aprovar exige reconhecer cada motivo da decisão."""

    decisao: DecisaoHumana
    operador: str | None = Field(default=None, max_length=80,
                                 description="sem login (sem banco): nome declarado; com login, vem da sessão e é ignorado")
    justificativa: str = Field(max_length=1000)
    motivos_reconhecidos: list[str] = Field(default_factory=list, max_length=50,
                                            description="códigos de motivo conferidos; na aprovação, todos")


class RevisaoHumana(Estrito):
    """Registro da decisão humana. Fica ao lado do registro do pipeline, que nunca é alterado."""

    decisao: DecisaoHumana
    operador: str
    usuario: str | None = Field(default=None, description="login autenticado; None = nome declarado (sem login)")
    justificativa: str
    motivos_reconhecidos: list[str]
    decisao_automatica: str
    sha256_registro: str = Field(description="sha256 do JSON do registro revisado: a decisão vale para esse conteúdo")
    revisada_em: str


class DocumentoResumo(Estrito):
    arquivo: str
    disposicao: str
    estado: Literal["APROVADO_AUTO", "AGUARDA_EMISSOR", "REVISAO_HUMANA", "FALHA_PROCESSAMENTO"]
    tipo: str | None
    fonte: str | None
    golden: str
    confianca_minima: str | None
    motivos: list[str]
    tokens: int
    custo_estimado_usd: float | None
    tempo_ms: int | None
    revisao: RevisaoHumana | None = None


class ExecucaoItem(Estrito):
    id: str
    criada_em: str
    estado: EstadoJob
    modo: Modo
    origem: Literal["amostras", "upload"]
    total: int
    concluidos: int
    contagem: dict[str, int]


class ExecucaoResumo(ExecucaoItem):
    concluida_em: str | None = None
    sem_ocr: bool
    extracoes_simuladas: bool = False
    erro: str | None = None
    versoes: dict[str, str] = Field(default_factory=dict)
    documentos: list[DocumentoResumo] = Field(default_factory=list)


class PaginaMeta(Estrito):
    numero: int
    total_paginas: int
    largura_pt: float
    altura_pt: float


class PaginaExecucoes(Estrito):
    itens: list[ExecucaoItem]
    total: int = Field(description="quantas execuções existem ao todo, para o front montar a paginação")
    limite: int
    deslocamento: int


class Erro(Estrito):
    detail: str
