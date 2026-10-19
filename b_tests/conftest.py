from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from lexis.a_domain.models import Extracao
from lexis.a_domain.ports import ChamadaLLM
from lexis.c_extraction.config import Config
from lexis.d_validation.reference_base import Golden
from lexis.f_application.pipeline import Contexto
from lexis.g_adapters.local_execution import carregar_golden, ingerir_arquivo
from lexis.g_adapters.local_storage import ArmazenamentoLocal

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "f_data" / "a_input"
GOLDEN_CSV = RAIZ / "f_data" / "c_golden_records" / "golden_records.csv"
REPLAY = RAIZ / "c_replay"


@pytest.fixture(scope="session")
def golden() -> Golden:
    return carregar_golden(GOLDEN_CSV)


@pytest.fixture
def ctx(golden: Golden) -> Contexto:
    return Contexto(golden=golden, modo="replay", cfg=Config(), gravacoes=ArmazenamentoLocal(REPLAY), usar_ocr=False)


@pytest.fixture
def ctx_entrega(golden: Golden) -> Contexto:
    """O que `lexis run` e `lexis avaliar` usam: replay COM a gravação de OCR (c_replay/<sha>/ocr.json).

    Em replay o OCR vem só da gravação, nunca do Tesseract da máquina, então continua independente do ambiente."""
    return Contexto(golden=golden, modo="replay", cfg=Config(), gravacoes=ArmazenamentoLocal(REPLAY), usar_ocr=True)


def extracao_replay(stem: str, etapa: str = "extracao") -> Extracao:
    sha = ingerir_arquivo(DOCS / f"{stem}.pdf").sha256
    dados = json.loads((REPLAY / sha / f"{etapa}.json").read_text(encoding="utf-8"))
    return Extracao.model_validate(dados["conteudo"])


def texto_do_pdf(stem: str) -> str:
    return ingerir_arquivo(DOCS / f"{stem}.pdf").texto


def criar_pdf(
    caminho: Path, linhas: list[str], *, ocultas: tuple[str, ...] = (), js: bool = False, fonte_oculta: float = 9,
    cmyk_branco: bool = False, render_invisivel: bool = False,
) -> Path:
    c = canvas.Canvas(str(caminho), pagesize=A4)
    y = 800.0
    c.setFont("Helvetica", 9)
    for linha in linhas:
        c.drawString(40, y, linha)
        y -= 13
    for oculto in ocultas:
        if cmyk_branco:
            c.setFillColorCMYK(0, 0, 0, 0)
        else:
            c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica", fonte_oculta)
        if render_invisivel:
            c.setFillColorRGB(0, 0, 0)
            t = c.beginText(40, 60)
            t.setTextRenderMode(3)
            t.textLine(oculto)
            c.drawText(t)
        else:
            c.drawString(40, 60, oculto)
    c.save()
    if js:  # objeto de ação JavaScript anexado ao final do arquivo (nada é executado em nenhum momento)
        with caminho.open("ab") as f:
            f.write(b"\n99 0 obj\n<< /Type /Action /S /JavaScript /JS (app.alert(1)) >>\nendobj\n")
    return caminho


class ExtratorFalso:
    """Extrator em memória: simula o provedor sem rede."""

    modelo = "falso"

    def __init__(self, extracao: Extracao) -> None:
        self.extracao = extracao
        self.recebido: list[str] = []

    def extrair_texto(self, texto: str, etapa: str = "extracao") -> tuple[Extracao, ChamadaLLM]:
        self.recebido.append(texto)
        return self.extracao, ChamadaLLM(etapa, self.modelo, "API")

    def transcrever(self, png: bytes) -> tuple[str, ChamadaLLM]:
        raise NotImplementedError

    def extrair_imagem(self, png: bytes) -> tuple[Extracao, ChamadaLLM]:
        raise NotImplementedError


def contexto_vivo(golden: Golden, falso: ExtratorFalso, replay: Path) -> Contexto:
    return Contexto(golden=golden, modo="live", cfg=Config(), gravacoes=ArmazenamentoLocal(replay), usar_ocr=False,
                    cliente_factory=lambda: falso)


def resposta_tool_use(entrada: dict[str, Any], nome: str = "registrar_extracao") -> Any:
    bloco = SimpleNamespace(type="tool_use", name=nome, input=entrada, id="tu_1")
    return SimpleNamespace(content=[bloco], usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def resposta_texto(texto: str) -> Any:
    bloco = SimpleNamespace(type="text", text=texto)
    return SimpleNamespace(content=[bloco], usage=SimpleNamespace(input_tokens=10, output_tokens=5))
