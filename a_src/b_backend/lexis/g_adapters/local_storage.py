"""Adaptadores locais das portas de armazenamento: sistema de arquivos (execução local) e memória (testes)."""

from __future__ import annotations

from pathlib import Path

from lexis.a_domain.ports import ArmazenamentoObjetos, ChaveInvalida

__all__ = ["ArmazenamentoComCache", "ArmazenamentoEmCamadas", "ArmazenamentoLocal", "ArmazenamentoMemoria", "ChaveInvalida"]


class ArmazenamentoLocal:
    """Chave -> arquivo sob `raiz`. Chaves que escapam da raiz (`..`, caminho absoluto) são rejeitadas."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz.resolve()

    def _caminho(self, chave: str) -> Path:
        alvo = (self.raiz / chave).resolve()
        if alvo != self.raiz and self.raiz not in alvo.parents:
            raise ChaveInvalida(f"chave fora da raiz: {chave!r}")
        return alvo

    def listar(self, prefixo: str = "") -> list[str]:
        if not self.raiz.exists():
            return []
        chaves = (p.relative_to(self.raiz).as_posix() for p in self.raiz.rglob("*") if p.is_file())
        return sorted(c for c in chaves if c.startswith(prefixo))

    def ler(self, chave: str) -> bytes | None:
        caminho = self._caminho(chave)
        return caminho.read_bytes() if caminho.is_file() else None

    def gravar(self, chave: str, conteudo: bytes) -> None:
        caminho = self._caminho(chave)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(conteudo)


class ArmazenamentoMemoria:
    def __init__(self, inicial: dict[str, bytes] | None = None) -> None:
        self.objetos: dict[str, bytes] = dict(inicial or {})

    def listar(self, prefixo: str = "") -> list[str]:
        return sorted(c for c in self.objetos if c.startswith(prefixo))

    def ler(self, chave: str) -> bytes | None:
        return self.objetos.get(chave)

    def gravar(self, chave: str, conteudo: bytes) -> None:
        self.objetos[chave] = conteudo


class ArmazenamentoComCache:
    """Saída de uma execução (`primario`) apoiada por um cache que sobrevive entre execuções.

    Leitura: o primário; na falta, o cache, e o que veio do cache é copiado para o primário (cada pasta de relatório
    fica completa, mesmo com documentos reaproveitados). Escrita: nos dois, mantendo o cache em dia."""

    def __init__(self, primario: ArmazenamentoObjetos, cache: ArmazenamentoObjetos) -> None:
        self.primario, self.cache = primario, cache

    def listar(self, prefixo: str = "") -> list[str]:
        return sorted(set(self.primario.listar(prefixo)) | set(self.cache.listar(prefixo)))

    def ler(self, chave: str) -> bytes | None:
        achado = self.primario.ler(chave)
        if achado is not None:
            return achado
        achado = self.cache.ler(chave)
        if achado is not None:
            self.primario.gravar(chave, achado)
        return achado

    def gravar(self, chave: str, conteudo: bytes) -> None:
        self.primario.gravar(chave, conteudo)
        self.cache.gravar(chave, conteudo)


class ArmazenamentoEmCamadas:
    """Lê do primário e, na falta, do secundário (somente leitura); grava SEMPRE no primário.

    Usado pela interface web: as gravações versionadas do repositório servem de cache de leitura, mas uma execução
    nunca as sobrescreve (as respostas novas ficam na pasta da própria execução).
    """

    def __init__(self, primario: ArmazenamentoObjetos, secundario: ArmazenamentoObjetos) -> None:
        self.primario, self.secundario = primario, secundario

    def listar(self, prefixo: str = "") -> list[str]:
        return sorted(set(self.primario.listar(prefixo)) | set(self.secundario.listar(prefixo)))

    def ler(self, chave: str) -> bytes | None:
        achado = self.primario.ler(chave)
        return achado if achado is not None else self.secundario.ler(chave)

    def gravar(self, chave: str, conteudo: bytes) -> None:
        self.primario.gravar(chave, conteudo)
