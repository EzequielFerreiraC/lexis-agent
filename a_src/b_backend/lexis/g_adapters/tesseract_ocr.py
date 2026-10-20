"""Adaptador da porta `LeitorOCR`: OCR local (Tesseract), leitor do scan independente do modelo.

Sem o binário, `ler` devolve None: o pipeline degrada e registra OCR_INDISPONIVEL. O núcleo nunca chama o Tesseract
direto; recebe `ler` por injeção (`Contexto.leitor_ocr`), e em replay usa só a gravação (`c_replay/<sha>/ocr.json`).
"""

from __future__ import annotations

import io
import shutil


def disponivel() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def ler(png: bytes) -> str | None:
    """Texto do OCR sobre a imagem pré-processada (cinza + autocontraste), ou None se indisponível."""
    if not disponivel():
        return None
    import pytesseract
    from PIL import Image, ImageOps

    try:
        img = ImageOps.autocontrast(Image.open(io.BytesIO(png)).convert("L"))
        langs = set(pytesseract.get_languages(config=""))
        texto: str = pytesseract.image_to_string(img, lang="por" if "por" in langs else "eng")
    except Exception:
        return None
    return texto.strip() or None
