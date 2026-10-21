"""Execução local: monta o contexto e liga os adaptadores (arquivos, Anthropic, Tesseract) às portas do núcleo."""

from __future__ import annotations

from pathlib import Path

from lexis.a_domain.models import RegistroSaida
from lexis.a_domain.ports import ArmazenamentoObjetos
from lexis.b_ingestion.pdf import DocumentoIngerido, ingerir_bytes
from lexis.c_extraction.config import Config
from lexis.d_validation.reference_base import Golden
from lexis.f_application.batch import Resultado, processar_lote
from lexis.f_application.pipeline import Contexto, processar_conteudo
from lexis.g_adapters import tesseract_ocr
from lexis.g_adapters.anthropic_api import ExtratorAnthropic, chamador_anthropic
from lexis.g_adapters.local_storage import ArmazenamentoComCache, ArmazenamentoLocal
from lexis.g_adapters.local_trail import TrilhaArquivo


def ingerir_arquivo(caminho: Path) -> DocumentoIngerido:
    """Lê o PDF do disco e delega ao núcleo, que trabalha só sobre bytes."""
    return ingerir_bytes(caminho.name, caminho.read_bytes())


def carregar_golden(caminho: Path) -> Golden:
    """Lê a base de referência (CSV) do disco; o núcleo a constrói a partir dos bytes."""
    return Golden.de_bytes(caminho.read_bytes())


def contexto_local(
    golden_csv: Path, modo: str, cfg: Config, dir_gravacoes: Path, *, usar_ocr: bool = True,
) -> Contexto:
    """Contexto da CLI: gravações em disco, modelo da Anthropic (criado só se faltar gravação) e OCR local."""
    return Contexto(
        golden=carregar_golden(golden_csv), modo=modo, cfg=cfg,
        gravacoes=ArmazenamentoLocal(dir_gravacoes), usar_ocr=usar_ocr,
        cliente_factory=lambda: ExtratorAnthropic(cfg), chamador_factory=chamador_anthropic,
        leitor_ocr=tesseract_ocr.ler,
    )


def processar_documento(caminho: Path, ctx: Contexto, run_id: str) -> RegistroSaida:
    return processar_conteudo(caminho.name, caminho.read_bytes(), ctx, run_id)


def executar_lote(
    entrada: Path, saida: Path, ctx: Contexto, forcar: bool = False, cache: Path | None = None,
) -> tuple[list[Resultado], str]:
    """`cache`: pasta que sobrevive entre execuções (cada `saida` é nova); o que já foi processado é reaproveitado."""
    destino: ArmazenamentoObjetos = ArmazenamentoLocal(saida)
    if cache is not None:
        destino = ArmazenamentoComCache(destino, ArmazenamentoLocal(cache))
    return processar_lote(
        ArmazenamentoLocal(entrada), destino, TrilhaArquivo(saida / "auditoria.jsonl"), ctx, forcar=forcar,
    )
