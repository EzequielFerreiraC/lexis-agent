"""Contratos de dados: o que o modelo devolve (Extracao) e o que o operador recebe (RegistroSaida)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.1"
MAX_TEXTO_LITERAL = 400


class Estrito(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TipoEvento(StrEnum):
    DIVIDENDO = "DIVIDENDO"
    JCP = "JCP"
    GRUPAMENTO = "GRUPAMENTO"
    DESDOBRAMENTO = "DESDOBRAMENTO"
    BONIFICACAO = "BONIFICACAO"
    OUTRO = "OUTRO"


class Situacao(StrEnum):
    PRESENTE = "PRESENTE"
    AUSENTE = "AUSENTE"
    A_DEFINIR = "A_DEFINIR"
    NAO_APLICAVEL = "NAO_APLICAVEL"


class LeituraCampo(Estrito):
    """Texto LITERAL copiado do documento. O modelo nunca devolve valores normalizados."""

    texto: str | None = Field(default=None, max_length=MAX_TEXTO_LITERAL)
    pagina: int | None = Field(default=None, ge=1)
    situacao: Situacao

    @model_validator(mode="after")
    def _presente_exige_texto(self) -> LeituraCampo:
        if self.situacao is Situacao.PRESENTE and not (self.texto and self.texto.strip()):
            raise ValueError("situacao PRESENTE exige texto literal")
        return self


class Extracao(Estrito):
    titulo: LeituraCampo
    tipo_evento_texto: LeituraCampo
    tipo_evento: TipoEvento
    campos: dict[str, LeituraCampo]

    @field_validator("campos")
    @classmethod
    def _campos_conhecidos(cls, v: dict[str, LeituraCampo]) -> dict[str, LeituraCampo]:
        from lexis.a_domain.specs import SPECS

        desconhecidos = set(v) - set(SPECS.campos)
        if desconhecidos:
            raise ValueError(f"campos desconhecidos: {sorted(desconhecidos)}")
        return v


# ----------------------------- saída -----------------------------


class EstadoCampo(StrEnum):
    EXTRAIDO = "EXTRAIDO"
    NAO_APLICAVEL = "NAO_APLICAVEL"
    AUSENTE = "AUSENTE"
    PENDENTE = "PENDENTE"
    INCERTO = "INCERTO"


class Nivel(StrEnum):
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAIXA = "BAIXA"


class Severidade(StrEnum):
    ERRO = "ERRO"
    AVISO = "AVISO"
    INFO = "INFO"


class Decisao(StrEnum):
    APROVADO_AUTO = "APROVADO_AUTO"
    AGUARDA_EMISSOR = "AGUARDA_EMISSOR"
    REVISAO_HUMANA = "REVISAO_HUMANA"
    FALHA_PROCESSAMENTO = "FALHA_PROCESSAMENTO"


class TipoAcao(StrEnum):
    CORRIGIR_EXTRACAO = "CORRIGIR_EXTRACAO"
    RESOLVER_INCONSISTENCIA = "RESOLVER_INCONSISTENCIA"
    CADASTRAR_EMISSOR = "CADASTRAR_EMISSOR"
    AGUARDAR_AVISO_COMPLEMENTAR = "AGUARDAR_AVISO_COMPLEMENTAR"
    CONFERIR_CLASSIFICACAO = "CONFERIR_CLASSIFICACAO"
    VERIFICAR_SEGURANCA = "VERIFICAR_SEGURANCA"
    REPROCESSAR = "REPROCESSAR"


class Evidencia(Estrito):
    pagina: int | None = None
    trecho: str | None = None
    bbox: list[float] | None = None
    fonte: str = "TEXTO_NATIVO"


class Confianca(Estrito):
    nivel: Nivel
    motivos: list[str]
    justificativa: str


class CampoSaida(Estrito):
    estado: EstadoCampo
    valor: str | None = None
    detalhe_valor: dict[str, str] | None = None
    natureza: str | None = None  # LITERAL | DERIVADO
    texto_literal: str | None = None
    evidencia: Evidencia | None = None
    confianca: Confianca


class RegraResultado(Estrito):
    id: str
    severidade: Severidade
    resultado: str  # OK | FALHA | NAO_APLICAVEL
    campos: list[str] = Field(default_factory=list)
    detalhe: str
    esperado: str | None = None
    observado: str | None = None


class Ficha(Estrito):
    """Ficha de conferência: o que o operador precisa checar, sem reabrir o PDF inteiro."""

    campo: str | None
    codigo: str
    tipo_acao: TipoAcao
    acao_sugerida: str
    esperado: str | None = None
    observado: str | None = None
    onde_conferir: Evidencia | None = None


class Motivo(Estrito):
    codigo: str
    mensagem: str
    campo: str | None = None


class PassoParaAprovar(Estrito):
    """Um bloqueio da decisão e o que aconteceria se só ele fosse resolvido (simulação sobre a tabela de decisão)."""

    codigo: str  # regra que falhou ou condição (CAMPO_CRITICO_FRACO, CAMPO_PENDENTE_NO_AVISO)
    campo: str | None = None
    linha_que_aciona: str  # linha da tabela que este bloqueio torna verdadeira (ex.: L2)
    condicao: str  # o que precisa passar a ser verdade
    decisao_se_so_este_resolver: Decisao
    linha_se_so_este_resolver: str


class ParaAprovar(Estrito):
    """O que falta para APROVADO_AUTO: cada bloqueio sozinho e todos juntos. Não reprocessa o documento: reavalia a
    tabela de decisão com o bloqueio resolvido, então efeitos indiretos (ex.: a confiança de outro campo) não entram."""

    passos: list[PassoParaAprovar]
    decisao_com_todos_resolvidos: Decisao
    linha_com_todos_resolvidos: str


class DecisaoSaida(Estrito):
    estado: Decisao
    resumo: str
    motivos: list[Motivo]
    linha_da_tabela: str
    para_aprovar: ParaAprovar | None = None  # só em REVISAO_HUMANA e AGUARDA_EMISSOR


class ValidacaoGolden(Estrito):
    status: str  # MATCH | PARTIAL_MISMATCH | NOT_FOUND | AMBIGUOUS | NAO_AVALIADO
    registro_golden: dict[str, str] | None = None
    comparacoes: list[dict[str, Any]] = Field(default_factory=list)
    sugestao_por_nome: dict[str, Any] | None = None


class ClassificacaoSaida(Estrito):
    tipo_final: TipoEvento
    tipo_modelo: TipoEvento
    por_zona: dict[str, str | None]
    pontuacao: dict[str, float]
    sinais: list[str]
    conflito_titulo_corpo: bool


class RegistroSaida(Estrito):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    documento: dict[str, Any]
    versoes: dict[str, str]
    decisao: DecisaoSaida
    evento: dict[str, Any]
    campos: dict[str, CampoSaida]
    validacao_golden: ValidacaoGolden
    regras: list[RegraResultado]
    fichas_conferencia: list[Ficha]
    auditoria: dict[str, Any]
