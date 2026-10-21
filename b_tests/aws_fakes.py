"""Cliente S3 falso (sem rede, sem boto3), com o formato de resposta/erro que o adaptador espera."""

from __future__ import annotations

import io
from typing import Any


class ErroCliente(Exception):
    def __init__(self, codigo: str) -> None:
        super().__init__(codigo)
        self.response = {"Error": {"Code": codigo}}


class _Paginador:
    def __init__(self, objetos: dict[tuple[str, str], bytes]) -> None:
        self.objetos = objetos

    def paginate(self, Bucket: str, Prefix: str = "") -> list[dict[str, Any]]:  # noqa: N803
        chaves = sorted(k for (b, k) in self.objetos if b == Bucket and k.startswith(Prefix))
        return [{"Contents": [{"Key": k} for k in chaves[i:i + 2]]} for i in range(0, len(chaves), 2)] or [{}]


class S3Falso:
    def __init__(self) -> None:
        self.objetos: dict[tuple[str, str], bytes] = {}
        self.escritas: list[dict[str, Any]] = []
        self.falhar_leitura = False

    def put(self, bucket: str, chave: str, conteudo: bytes) -> None:
        self.objetos[(bucket, chave)] = conteudo

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if self.falhar_leitura:
            raise ErroCliente("SlowDown")
        if (Bucket, Key) not in self.objetos:
            raise ErroCliente("NoSuchKey")
        dados = self.objetos[(Bucket, Key)]
        return {"Body": io.BytesIO(dados), "ContentLength": len(dados)}

    def put_object(self, Bucket: str, Key: str, Body: bytes, **extra: Any) -> None:  # noqa: N803
        self.objetos[(Bucket, Key)] = Body
        self.escritas.append({"Bucket": Bucket, "Key": Key, **extra})

    def get_paginator(self, nome: str) -> _Paginador:
        assert nome == "list_objects_v2"
        return _Paginador(self.objetos)
