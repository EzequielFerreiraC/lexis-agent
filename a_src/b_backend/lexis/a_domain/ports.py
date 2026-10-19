"""Portas do núcleo: tudo que o domínio precisa do mundo externo, sem saber quem fornece.

Cada porta tem um adaptador em `g_adapters/` (arquivos/memória, S3, logs, Anthropic/Bedrock, Tesseract) e um equivalente em nuvem
documentado em `e_docs/c_architecture/aws.md` (S3, DynamoDB, CloudWatch, Bedrock...). Trocar o adaptador não muda
nenhuma regra de negócio.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from lexis.a_domain.models import Extracao, TipoEvento


class ArmazenamentoObjetos(Protocol):
    """Armazém chave -> bytes (equivale a um bucket S3). Usado para documentos, resultados e gravações."""

    def listar(self, prefixo: str = "") -> list[str]: ...

    def ler(self, chave: str) -> bytes | None:
        """None quando a chave não existe."""
        ...

    def gravar(self, chave: str, conteudo: bytes) -> None: ...


class TrilhaAuditoria(Protocol):
    """Registro append-only de eventos (equivale a CloudWatch Logs / Firehose -> S3 com Object Lock)."""

    def registrar(self, evento: dict[str, Any]) -> None: ...


class ChaveInvalida(ValueError):
    """Chave de armazenamento que tenta escapar da raiz (`..`, caminho absoluto) ou é vazia."""


class ErroExtracao(Exception):
    def __init__(self, codigo: str, detalhe: str, *, tokens_entrada: int = 0, tokens_saida: int = 0) -> None:
        super().__init__(f"{codigo}: {detalhe}")
        self.codigo = codigo
        self.detalhe = detalhe
        # tokens já gastos antes da falha: contam no custo e no orçamento mesmo sem resultado
        self.tokens_entrada = tokens_entrada
        self.tokens_saida = tokens_saida


@dataclass
class ChamadaLLM:
    etapa: str
    modelo: str
    origem: str  # API | CACHE
    tokens_entrada: int = 0
    tokens_saida: int = 0
    latencia_ms: int = 0
    reparos: int = 0
    origem_fixture: str | None = None
    aviso: str | None = None


class Extrator(Protocol):
    """Provedor de leitura por modelo (Anthropic direto, Bedrock, ou gravações em replay)."""

    modelo: str

    def extrair_texto(self, texto: str, etapa: str = "extracao") -> tuple[Extracao, ChamadaLLM]: ...

    def transcrever(self, png: bytes) -> tuple[str, ChamadaLLM]: ...

    def extrair_imagem(self, png: bytes) -> tuple[Extracao, ChamadaLLM]: ...


# Executa UMA chamada de tool pedida pelo modelo e devolve (conteúdo do tool_result, é_erro).
# Quem implementa (o orquestrador) aplica allow-list e confere os argumentos; o modelo nunca executa nada.
Atender = Callable[[str, dict[str, Any]], tuple[dict[str, Any], bool]]


@dataclass(frozen=True)
class PedidoTools:
    """O que o orquestrador oferece ao modelo: o registro já normalizado e SÓ as tools aplicáveis ao tipo."""

    tipo: TipoEvento
    registro: dict[str, str]
    ferramentas: list[dict[str, Any]]

    @property
    def nomes(self) -> list[str]:
        return [str(f["name"]) for f in self.ferramentas]


@dataclass
class ConversaTools:
    """Transcrição do function calling de validação: o que o modelo pediu, o que recebeu e o parecer final.

    `turnos[i]["chamadas"]` = [{"tool", "argumentos", "resultado", "erro"}]. O parecer é informativo: a decisão
    vem sempre do resultado das tools (código), nunca do texto do modelo."""

    turnos: list[dict[str, Any]] = field(default_factory=list)
    parecer: str | None = None
    encerramento: str | None = None  # stop_reason final (end_turn, max_tokens, LIMITE_DE_TURNOS...)
    chamada: ChamadaLLM | None = None
    avisos: list[str] = field(default_factory=list)


# OCR local: imagem PNG -> texto, ou None se o leitor estiver indisponível. Adaptador: g_adapters/tesseract_ocr.py.
LeitorOCR = Callable[[bytes], str | None]


class ChamadorDeTools(Protocol):
    """Conduz o function calling: o modelo pede tools, `atender` executa, o resultado volta ao modelo."""

    def conduzir(self, pedido: PedidoTools, atender: Atender) -> ConversaTools: ...
