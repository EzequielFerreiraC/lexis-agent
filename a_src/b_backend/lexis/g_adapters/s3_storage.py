"""Adaptador S3 da porta ArmazenamentoObjetos. `boto3` é dependência OPCIONAL (extra `aws`) e só é importado
quando nenhum cliente é injetado. Em testes injeta-se um cliente falso, sem rede e sem credenciais."""

from __future__ import annotations

from typing import Any

from lexis.a_domain.ports import ChaveInvalida


class ObjetoGrandeDemais(Exception):
    def __init__(self, chave: str, tamanho: int, limite: int) -> None:
        super().__init__(f"{chave}: {tamanho} bytes > limite de {limite}")
        self.tamanho = tamanho
        self.limite = limite


def _chave_segura(chave: str) -> str:
    if not chave or chave.startswith("/") or ".." in chave.split("/") or "\x00" in chave:
        raise ChaveInvalida(f"chave inválida: {chave!r}")
    return chave


def _nao_existe(erro: Exception) -> bool:
    codigo = getattr(erro, "response", {}).get("Error", {}).get("Code")
    return codigo in {"NoSuchKey", "404", "NotFound"}


class ArmazenamentoS3:
    """Chave lógica -> objeto `<prefixo><chave>` no bucket.

    Em produção: criptografia em repouso com KMS (`kms_key_id`), acesso por IAM de menor privilégio
    (s3:GetObject / s3:PutObject / s3:ListBucket só nos prefixos usados) e Block Public Access ligado.
    """

    def __init__(
        self, bucket: str, prefixo: str = "", *, cliente: Any | None = None,
        kms_key_id: str | None = None, limite_bytes: int | None = None,
    ) -> None:
        if cliente is None:
            import boto3  # extra opcional: pip install 'lexis[aws]'

            cliente = boto3.client("s3")
        self.cliente, self.bucket = cliente, bucket
        self.prefixo = prefixo if not prefixo or prefixo.endswith("/") else prefixo + "/"
        self.kms_key_id, self.limite_bytes = kms_key_id, limite_bytes

    def _s3(self, chave: str) -> str:
        return self.prefixo + _chave_segura(chave)

    def listar(self, prefixo: str = "") -> list[str]:
        chaves: list[str] = []
        paginas = self.cliente.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=self.prefixo + prefixo)
        for pagina in paginas:
            chaves += [o["Key"][len(self.prefixo):] for o in pagina.get("Contents", [])]
        return sorted(chaves)

    def ler(self, chave: str) -> bytes | None:
        try:
            resp = self.cliente.get_object(Bucket=self.bucket, Key=self._s3(chave))
        except Exception as e:
            if _nao_existe(e):
                return None
            raise
        tamanho = int(resp.get("ContentLength", 0))
        if self.limite_bytes is not None and tamanho > self.limite_bytes:
            raise ObjetoGrandeDemais(chave, tamanho, self.limite_bytes)
        corpo: bytes = resp["Body"].read()
        return corpo

    def gravar(self, chave: str, conteudo: bytes) -> None:
        extra: dict[str, Any] = {}
        if self.kms_key_id:
            extra = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self.kms_key_id}
        self.cliente.put_object(Bucket=self.bucket, Key=self._s3(chave), Body=conteudo, **extra)
