"""Confiança por campo: níveis discretos (ALTA/MEDIA/BAIXA) derivados de sinais objetivos, sempre com motivos."""

from __future__ import annotations

from dataclasses import dataclass

from lexis.a_domain.models import EstadoCampo, Nivel
from lexis.a_domain.specs import SPECS

ORDEM_NIVEL = {Nivel.BAIXA: 0, Nivel.MEDIA: 1, Nivel.ALTA: 2}


def min_nivel(a: Nivel, b: Nivel) -> Nivel:
    return a if ORDEM_NIVEL[a] <= ORDEM_NIVEL[b] else b


@dataclass
class EntradaConfianca:
    campo: str
    estado: EstadoCampo
    obrigatorio: bool
    fonte_scan: bool
    pagina: int | None
    regras_erro: list[str]
    regras_aviso: list[str]
    confirmacoes: list[str]
    leituras_concordam: bool | None = None
    ocr: bool | None = None  # True corrobora | False não corrobora | None indisponível
    ocr_disponivel: bool = False


def avaliar_confianca(e: EntradaConfianca) -> tuple[Nivel, list[str], str]:
    motivos: list[str] = []
    if e.estado is EstadoCampo.NAO_APLICAVEL:
        nivel, motivos = Nivel.ALTA, ["não se aplica ao tipo de evento (matriz de aplicabilidade)"]
    elif e.estado is EstadoCampo.PENDENTE:
        nivel, motivos = Nivel.ALTA, ["o aviso declara expressamente que a informação será divulgada depois"]
    elif e.estado is EstadoCampo.AUSENTE:
        if e.obrigatorio:
            nivel, motivos = Nivel.BAIXA, ["campo obrigatório para o tipo de evento não foi encontrado"]
        else:
            nivel, motivos = Nivel.MEDIA, ["campo opcional não consta no aviso (ausência não é provável apenas pela leitura)"]
    elif e.estado is EstadoCampo.INCERTO:
        nivel, motivos = Nivel.BAIXA, ["valor não verificável ou leituras divergentes"]
    else:
        nivel = Nivel.ALTA
        motivos.append(f"trecho literal verificado no texto-fonte (página {e.pagina})" if e.pagina else "trecho literal verificado")
        motivos.append("valor normalizado pelo código a partir do trecho")
        motivos += e.confirmacoes

    if e.estado is EstadoCampo.EXTRAIDO and e.fonte_scan:
        teto = Nivel(SPECS.politica["teto_confianca_scan"])
        nivel = min_nivel(nivel, teto)
        motivos.append("fonte é imagem (scan): leitura por modelo de visão, confiança limitada ao teto da política")
        if e.leituras_concordam:
            motivos.append("duas leituras por métodos diferentes concordam")
        if e.ocr is True:
            motivos.append("OCR local corrobora o valor")
        elif e.ocr is None and not e.ocr_disponivel:
            motivos.append("OCR local indisponível: sem leitor independente do modelo")
    if e.regras_erro:
        nivel = Nivel.BAIXA
        motivos.append("regra reprovada: " + ", ".join(sorted(set(e.regras_erro))))
    elif e.regras_aviso:
        nivel = min_nivel(nivel, Nivel.MEDIA)
        motivos.append("alerta: " + ", ".join(sorted(set(e.regras_aviso))))
    justificativa = f"{nivel.value}: " + "; ".join(motivos) + "."
    return nivel, motivos, justificativa
