"""Gravações das chamadas ao modelo (idempotência e replay), endereçadas pelo SHA-256 do documento.

Chave: `<sha256>/<etapa>.json`. Endereçar pelo conteúdo evita varreduras, sobrevive a renomeações e
mapeia direto para S3 (prefixo = sha) ou DynamoDB (partition key = sha, sort key = etapa).

Etapas: `extracao`, `transcricao`, `extracao_transcricao`, `extracao_direta` (leitura do documento) e
`validacao_tools` (a conversa de function calling sobre o registro já extraído) e `ocr` (texto do OCR local
do scan, para que o replay não dependa do Tesseract instalado na máquina).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from lexis.a_domain.models import Extracao
from lexis.a_domain.ports import (
    ArmazenamentoObjetos,
    Atender,
    ChamadaLLM,
    ChamadorDeTools,
    ConversaTools,
    ErroExtracao,
    Extrator,
    PedidoTools,
)
from lexis.c_extraction.prompts import sha_prompt

ETAPA_TOOLS = "validacao_tools"
ETAPA_OCR = "ocr"


def chave_gravacao(sha_pdf: str, etapa: str) -> str:
    return f"{sha_pdf}/{etapa}.json"


class _Gravacoes:
    """Leitura e escrita de gravações de um documento. modo: 'replay' | 'auto' | 'live'."""

    def __init__(self, armazem: ArmazenamentoObjetos, sha_pdf: str, modo: str, nome: str) -> None:
        self.armazem, self.sha, self.modo, self.nome = armazem, sha_pdf, modo, nome

    def _ler(self, etapa: str) -> dict[str, Any] | None:
        if self.modo == "live":
            return None
        bruto = self.armazem.ler(chave_gravacao(self.sha, etapa))
        if bruto is None:
            return None
        try:
            dados: dict[str, Any] = json.loads(bruto)
        except ValueError as e:
            raise ErroExtracao("FIXTURE_ILEGIVEL", chave_gravacao(self.sha, etapa)) from e
        if dados.get("pdf_sha256") != self.sha:
            raise ErroExtracao("FIXTURE_DESATUALIZADA", f"{chave_gravacao(self.sha, etapa)} não corresponde ao PDF")
        if dados.get("origem") == "API" and dados.get("prompt_sha") != sha_prompt():
            if self.modo == "auto":
                return None  # prompt mudou: chama o modelo de novo e regrava
            # replay: reproduzir a resposta a outro prompt gravaria no registro um `prompt_sha` que não a produziu
            raise ErroExtracao("GRAVACAO_PROMPT_DIVERGENTE",
                               f"{chave_gravacao(self.sha, etapa)} foi gravada com outro prompt; regrave com --modo live")
        return dados

    def _gravar(self, etapa: str, conteudo: Any, meta: ChamadaLLM, **extra: Any) -> None:
        registro = {
            "formato": 1, "etapa": etapa, "documento": self.nome, "pdf_sha256": self.sha, "origem": "API",
            "modelo": meta.modelo, "prompt_sha": sha_prompt(), **extra, "conteudo": conteudo,
            "uso": {"tokens_entrada": meta.tokens_entrada, "tokens_saida": meta.tokens_saida,
                    "latencia_ms": meta.latencia_ms, "reparos": meta.reparos},
        }
        if meta.aviso:
            registro["aviso"] = meta.aviso
        self.armazem.gravar(
            chave_gravacao(self.sha, etapa),
            (json.dumps(registro, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )

    @staticmethod
    def _meta_do_cache(etapa: str, cache: dict[str, Any]) -> ChamadaLLM:
        # `_ler` já recusou gravação da API feita com outro prompt: o que chega aqui foi gravado com o prompt atual
        return ChamadaLLM(etapa, str(cache.get("modelo", "?")), "CACHE", origem_fixture=str(cache.get("origem")),
                          aviso=cache.get("aviso"))


class ExtratorComCache(_Gravacoes):
    """Embrulha um extrator ao vivo (ou nenhum) com gravações por etapa.

    modo: 'replay' (só gravações; falta = erro) | 'auto' (gravação, senão API) | 'live' (sempre API, regrava).
    `interno` pode ser uma fábrica: o extrator ao vivo só é criado num acerto negativo do cache, então um lote
    100% gravado roda sem chave de API e sem criar cliente.
    """

    def __init__(
        self, interno: Extrator | Callable[[], Extrator | None] | None, armazem: ArmazenamentoObjetos, sha_pdf: str,
        modo: str, nome: str = "",
    ) -> None:
        if modo != "replay" and interno is None:
            raise ErroExtracao("SEM_EXTRATOR", f"modo {modo} exige um extrator ao vivo")
        super().__init__(armazem, sha_pdf, modo, nome)
        self._interno = interno
        self.modelo = "replay" if interno is None else "ao-vivo"

    @property
    def interno(self) -> Extrator | None:
        if callable(self._interno):  # fábrica: instancia na primeira necessidade
            self._interno = self._interno()
        return self._interno

    def _etapa(
        self, etapa: str, chamar: Callable[[Extrator], Any], para_json: Callable[[Any], Any],
        de_json: Callable[[Any], Any],
    ) -> tuple[Any, ChamadaLLM]:
        cache = self._ler(etapa)
        if cache is not None:
            return de_json(cache["conteudo"]), self._meta_do_cache(etapa, cache)
        if self.interno is None:
            raise ErroExtracao("FIXTURE_AUSENTE", f"sem gravação para {self.sha[:12]}/{etapa} (modo replay)")
        valor, meta = chamar(self.interno)
        self._gravar(etapa, para_json(valor), meta)
        return valor, meta

    def extrair_texto(self, texto: str, etapa: str = "extracao") -> tuple[Extracao, ChamadaLLM]:
        return self._etapa(etapa, lambda i: i.extrair_texto(texto, etapa),
                           lambda e: e.model_dump(mode="json"), Extracao.model_validate)

    def transcrever(self, png: bytes) -> tuple[str, ChamadaLLM]:
        return self._etapa("transcricao", lambda i: i.transcrever(png),
                           lambda t: {"texto": t}, lambda c: str(c["texto"]))

    def extrair_imagem(self, png: bytes) -> tuple[Extracao, ChamadaLLM]:
        return self._etapa("extracao_direta", lambda i: i.extrair_imagem(png),
                           lambda e: e.model_dump(mode="json"), Extracao.model_validate)

    def ler_ocr(self, png: bytes, leitor: Callable[[bytes], str | None]) -> str | None:
        """OCR local como etapa gravada: o replay depende só de `c_replay/`, nunca do Tesseract da máquina.

        replay: só a gravação (sem gravação = OCR indisponível) · auto: gravação, senão o leitor local ·
        live: sempre o leitor local. Só leitura bem-sucedida é gravada: "indisponível" não vira fato permanente.
        """
        cache = self._ler(ETAPA_OCR)
        if cache is not None:
            return str(cache["conteudo"]["texto"])
        if self.modo == "replay":
            return None
        texto = leitor(png)
        if texto is not None:
            registro = {"formato": 1, "etapa": ETAPA_OCR, "documento": self.nome, "pdf_sha256": self.sha,
                        "origem": "OCR_LOCAL", "conteudo": {"texto": texto}}
            self.armazem.gravar(chave_gravacao(self.sha, ETAPA_OCR),
                                (json.dumps(registro, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        return texto


def assinatura_pedido(pedido: PedidoTools) -> str:
    """Hash do que o modelo recebeu (registro, tools oferecidas, prompts): se mudar, a gravação não vale mais.

    O registro entra como lista de pares: a ORDEM em que o modelo vê os campos muda o que ele responde."""
    base = json.dumps({"tipo": pedido.tipo.value, "registro": list(pedido.registro.items()),
                       "ferramentas": pedido.ferramentas, "prompt_sha": sha_prompt()},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


class ChamadorComCache(_Gravacoes):
    """Function calling com gravação. Em replay, as tools que o MODELO pediu são reexecutadas pelo código.

    A gravação guarda o que o modelo pediu e o que recebeu; na reprodução, cada pedido passa de novo por `atender`
    (allow-list, conferência de argumentos e execução real) e o resultado é comparado com o gravado. Nada do
    veredito vem da gravação: ela só reproduz QUEM pediu QUAL tool com QUAIS argumentos.
    """

    def __init__(
        self, interno: ChamadorDeTools | Callable[[], ChamadorDeTools | None] | None, armazem: ArmazenamentoObjetos,
        sha_pdf: str, modo: str, nome: str = "",
    ) -> None:
        super().__init__(armazem, sha_pdf, modo, nome)
        self._interno = interno
        self.ultima: ConversaTools | None = None  # para o pipeline contabilizar tokens/custo da conversa

    @property
    def interno(self) -> ChamadorDeTools | None:
        if callable(self._interno):  # fábrica: instancia na primeira necessidade
            self._interno = self._interno()
        return self._interno

    def conduzir(self, pedido: PedidoTools, atender: Atender) -> ConversaTools:
        assinatura = assinatura_pedido(pedido)
        cache = self._ler(ETAPA_TOOLS)
        if cache is not None and cache.get("pedido_sha") == assinatura:
            self.ultima = self._reproduzir(cache, atender)
            return self.ultima
        if self.modo == "replay":
            codigo = "GRAVACAO_DESATUALIZADA" if cache is not None else "GRAVACAO_AUSENTE"
            raise ErroExtracao(codigo, chave_gravacao(self.sha, ETAPA_TOOLS))
        if self.interno is None:
            raise ErroExtracao("SEM_CHAMADOR_DE_TOOLS", "o extrator ao vivo não oferece function calling")
        conversa = self.ultima = self.interno.conduzir(pedido, atender)
        # conversa interrompida por erro não é gravada: reproduzi-la repetiria a falha, não o modelo
        if conversa.chamada is not None and not (conversa.encerramento or "").startswith("ERRO:"):
            self._gravar(ETAPA_TOOLS, {"turnos": conversa.turnos, "parecer": conversa.parecer,
                                       "encerramento": conversa.encerramento},
                         conversa.chamada, pedido_sha=assinatura)
        return conversa

    def _reproduzir(self, cache: dict[str, Any], atender: Atender) -> ConversaTools:
        conteudo = cache["conteudo"]
        divergentes: list[str] = []
        turnos: list[dict[str, Any]] = []
        for turno in conteudo.get("turnos", []):
            chamadas = []
            for c in turno.get("chamadas", []):
                resultado, erro = atender(str(c["tool"]), dict(c.get("argumentos") or {}))
                if resultado != c.get("resultado") or erro != c.get("erro"):
                    divergentes.append(str(c["tool"]))
                chamadas.append({**c, "resultado": resultado, "erro": erro})
            turnos.append({**turno, "chamadas": chamadas})
        avisos = [f"resultado atual difere do gravado (o parecer foi escrito sobre o anterior): {', '.join(divergentes)}"
                  ] if divergentes else []
        return ConversaTools(turnos=turnos, parecer=conteudo.get("parecer"), encerramento=conteudo.get("encerramento"),
                             chamada=self._meta_do_cache(ETAPA_TOOLS, cache), avisos=avisos)
