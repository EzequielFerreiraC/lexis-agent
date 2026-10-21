"""Arquitetura hexagonal como teste: o núcleo (a_ a f_) não faz I/O e não conhece adaptadores.

Falha se uma camada do núcleo importar biblioteca de I/O (rede, OCR, nuvem, banco, web), importar `g_adapters`,
`h_interfaces` ou `i_assessment`, importar uma camada acima da sua, ler `os.environ`, abrir/gravar arquivo ou
imprimir. Tudo isso entra por porta (`a_domain/ports.py`) e é ligado pelas entradas.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2] / "a_src" / "b_backend" / "lexis"
NUCLEO = ("a_domain", "b_ingestion", "c_extraction", "d_validation", "e_decision", "f_application")
CAMADAS = (*NUCLEO, "g_adapters", "h_interfaces", "i_assessment")

PROIBIDOS = {
    "anthropic", "pytesseract", "boto3", "botocore", "sqlalchemy", "pymysql", "fastapi", "starlette", "uvicorn",
    "httpx", "requests", "urllib", "socket", "subprocess", "shutil", "os", "sys",
}
METODOS_DE_ARQUIVO = {"read_bytes", "read_text", "write_bytes", "write_text", "mkdir", "unlink", "rmdir", "touch"}
# Exceção única e consciente: o catálogo de regras vem empacotado com o código e é lido uma vez, ao importar
PERMITIDOS = {("a_domain/specs.py", "read_bytes")}


def _arquivos(camada: str) -> list[Path]:
    return sorted((RAIZ / camada).rglob("*.py"))


def _relativo(p: Path) -> str:
    return p.relative_to(RAIZ).as_posix()


def _imports(arvore: ast.AST) -> list[str]:
    nomes: list[str] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes += [a.name for a in no.names]
        elif isinstance(no, ast.ImportFrom) and no.module and not no.level:
            nomes.append(no.module)
    return nomes


@pytest.mark.parametrize("camada", NUCLEO)
def test_nucleo_nao_importa_io_nem_adaptadores_nem_camada_acima(camada):
    problemas = []
    nivel = CAMADAS.index(camada)
    for arq in _arquivos(camada):
        for nome in _imports(ast.parse(arq.read_text(encoding="utf-8"))):
            raiz = nome.split(".")[0]
            if raiz in PROIBIDOS:
                problemas.append(f"{_relativo(arq)} importa {nome}")
            partes = nome.split(".")
            if raiz == "lexis" and len(partes) > 1 and partes[1] in CAMADAS and CAMADAS.index(partes[1]) > nivel:
                problemas.append(f"{_relativo(arq)} importa camada acima: {nome}")
    assert problemas == []


@pytest.mark.parametrize("camada", NUCLEO)
def test_nucleo_nao_abre_arquivo_nem_imprime_nem_le_ambiente(camada):
    problemas = []
    for arq in _arquivos(camada):
        rel = _relativo(arq)
        for no in ast.walk(ast.parse(arq.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id in {"open", "print", "input"}:
                problemas.append(f"{rel}:{no.lineno} chama {no.func.id}()")
            if (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
                    and no.func.attr in METODOS_DE_ARQUIVO and (rel, no.func.attr) not in PERMITIDOS):
                problemas.append(f"{rel}:{no.lineno} chama .{no.func.attr}()")
            if isinstance(no, ast.Attribute) and no.attr in {"environ", "getenv"}:
                problemas.append(f"{rel}:{no.lineno} lê o ambiente")
    assert problemas == []


def test_camadas_externas_tambem_respeitam_a_ordem():
    """g_adapters não importa h_ nem i_; i_assessment não importa h_. (h_ pode importar i_ para `lexis avaliar`.)"""
    regras = {"g_adapters": {"h_interfaces", "i_assessment"}, "i_assessment": {"h_interfaces"}}
    problemas = []
    for camada, proibidas in regras.items():
        for arq in _arquivos(camada):
            for nome in _imports(ast.parse(arq.read_text(encoding="utf-8"))):
                partes = nome.split(".")
                if partes[0] == "lexis" and len(partes) > 1 and partes[1] in proibidas:
                    problemas.append(f"{_relativo(arq)} importa {nome}")
    assert problemas == []


def test_o_teste_enxerga_o_codigo():
    """Garante que o teste não passa por não achar arquivos (ex.: pasta renomeada)."""
    assert all(_arquivos(c) for c in NUCLEO)
