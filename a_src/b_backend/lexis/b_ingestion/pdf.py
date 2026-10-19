"""Ingestão segura de PDF: nada é executado; só texto, imagens e metadados estruturais são lidos."""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from typing import Any

import pdfplumber

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGINAS = 20
MIN_CHARS_PAGINA_NATIVA = 30
_ATIVO = re.compile(rb"/(JavaScript|JS|OpenAction|Launch|EmbeddedFile|RichMedia)(?![A-Za-z])")
_TR3 = re.compile(rb"(?<![\w.])3\s+Tr(?![A-Za-z])")


class IngestaoErro(Exception):
    """Arquivo rejeitado antes de qualquer chamada externa."""

    def __init__(self, codigo: str, detalhe: str) -> None:
        super().__init__(f"{codigo}: {detalhe}")
        self.codigo = codigo
        self.detalhe = detalhe


@dataclass
class Pagina:
    numero: int
    texto: str  # somente texto visível
    texto_total: str  # inclui texto oculto (usado só para detectar injeção)
    imagens: int
    sem_texto: bool


@dataclass
class DocumentoIngerido:
    nome: str
    conteudo: bytes
    sha256: str
    paginas: list[Pagina]
    fonte: str  # NATIVO | SCAN | MISTO
    avisos: list[dict[str, str]] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return "\n".join(p.texto for p in self.paginas)

    @property
    def texto_total(self) -> str:
        return "\n".join(p.texto_total for p in self.paginas)

    def paginas_scan(self) -> list[int]:
        return [p.numero for p in self.paginas if p.sem_texto]

    def meta(self) -> dict[str, Any]:
        return {
            "arquivo": self.nome,
            "sha256": self.sha256,
            "paginas": len(self.paginas),
            "fonte": self.fonte,
            "avisos_ingestao": self.avisos,
        }


def sha256_bytes(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def _cor_clara(cor: Any) -> bool:
    """Branco/quase branco em escala de cinza (1), RGB (3) ou CMYK (4, onde branco é ~0,0,0,0)."""
    if cor is None:
        return False
    valores = cor if isinstance(cor, (tuple, list)) else (cor,)
    try:
        nums = [float(v) for v in valores]
    except (TypeError, ValueError):
        return False
    if len(nums) == 4:
        return all(v <= 0.03 for v in nums)
    return len(nums) in (1, 3) and all(v >= 0.97 for v in nums)


def _caractere_oculto(c: dict[str, Any], largura: float, altura: float) -> bool:
    fora = c["x1"] < 0 or c["x0"] > largura or c["bottom"] < 0 or c["top"] > altura
    return bool(fora or float(c.get("size") or 0) < 2 or _cor_clara(c.get("non_stroking_color")))


def _usa_render_mode_invisivel(pg: Any) -> bool:
    """Modo de renderização 3 (`3 Tr`): texto que o leitor não desenha, mas o extrator lê."""
    try:
        from pdfminer.pdftypes import resolve1

        fluxos = resolve1(pg.page_obj.contents)
        fluxos = fluxos if isinstance(fluxos, list) else [fluxos]
        return any(_TR3.search(resolve1(f).get_data()) for f in fluxos)
    except Exception:
        return False


def ingerir_bytes(nome: str, dados: bytes) -> DocumentoIngerido:
    if len(dados) > MAX_BYTES:
        raise IngestaoErro("ARQUIVO_GRANDE_DEMAIS", f"{len(dados)} bytes > {MAX_BYTES}")
    if not dados.startswith(b"%PDF-"):
        raise IngestaoErro("NAO_E_PDF", "assinatura %PDF- ausente")

    avisos: list[dict[str, str]] = []
    ativos = sorted({m.decode() for m in _ATIVO.findall(dados)})
    if ativos:
        avisos.append({"codigo": "CONTEUDO_ATIVO_PDF", "detalhe": ", ".join(ativos)})

    paginas: list[Pagina] = []
    try:
        with pdfplumber.open(io.BytesIO(dados)) as pdf:
            if len(pdf.pages) > MAX_PAGINAS:
                raise IngestaoErro("PAGINAS_DEMAIS", f"{len(pdf.pages)} > {MAX_PAGINAS}")
            for i, pg in enumerate(pdf.pages, start=1):
                visivel = pg.filter(lambda o, w=pg.width, h=pg.height: (  # type: ignore[misc]
                    o.get("object_type") != "char" or not _caractere_oculto(o, w, h)
                ))
                texto = (visivel.extract_text() or "").strip()
                total = (pg.extract_text() or "").strip()
                if len(total) > len(texto) + 3:
                    ocultos = "".join(
                        c["text"] for c in pg.chars if _caractere_oculto(c, pg.width, pg.height)
                    )
                    avisos.append({
                        "codigo": "TEXTO_OCULTO",
                        "detalhe": f"página {i}: {len(ocultos)} caracteres invisíveis excluídos do texto",
                    })
                if _usa_render_mode_invisivel(pg):
                    avisos.append({
                        "codigo": "TEXTO_OCULTO",
                        "detalhe": f"página {i}: texto em modo de renderização invisível (3 Tr); não é possível separá-lo",
                    })
                paginas.append(Pagina(
                    numero=i, texto=texto, texto_total=total, imagens=len(pg.images),
                    sem_texto=len(texto) < MIN_CHARS_PAGINA_NATIVA and len(pg.images) > 0,
                ))
    except IngestaoErro:
        raise
    except Exception as e:  # PDF corrompido ou com estrutura inesperada
        raise IngestaoErro("PDF_ILEGIVEL", type(e).__name__) from e

    if not paginas:
        raise IngestaoErro("PDF_VAZIO", "nenhuma página")
    com_scan = sum(p.sem_texto for p in paginas)
    fonte = "NATIVO" if com_scan == 0 else "SCAN" if com_scan == len(paginas) else "MISTO"
    if fonte == "NATIVO" and all(len(p.texto) < MIN_CHARS_PAGINA_NATIVA for p in paginas):
        raise IngestaoErro("SEM_CONTEUDO", "sem texto e sem imagem")
    return DocumentoIngerido(nome, dados, sha256_bytes(dados), paginas, fonte, avisos)


def renderizar_pagina_png(doc: DocumentoIngerido, numero: int, dpi: int = 200) -> bytes:
    with pdfplumber.open(io.BytesIO(doc.conteudo)) as pdf:
        img = pdf.pages[numero - 1].to_image(resolution=dpi).original
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def localizar_bbox(doc: DocumentoIngerido, numero: int, trecho: str) -> list[float] | None:
    """Caixa do trecho na página (pontos PDF), ou None se não localizável (ex.: quebra de linha)."""
    palavras = [re.escape(p) for p in trecho.split()]
    if not palavras:
        return None
    try:
        with pdfplumber.open(io.BytesIO(doc.conteudo)) as pdf:
            achados = pdf.pages[numero - 1].search(r"\s+".join(palavras), regex=True, case=False)
    except Exception:
        return None
    if not achados:
        return None
    a = achados[0]
    return [round(float(a[k]), 1) for k in ("x0", "top", "x1", "bottom")]
