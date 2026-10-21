"""Handler AWS Lambda: um documento por evento S3 (direto ou encapsulado em SQS).

Configuração por variáveis de ambiente (nenhum segredo no código):
  LEXIS_BUCKET_ENTRADA      bucket de PDFs; eventos de OUTROS buckets são rejeitados (confused deputy)
  LEXIS_BUCKET_SAIDA        bucket dos JSONs de saída (prefixo `json/`)
  LEXIS_BUCKET_GRAVACOES    bucket das gravações de extração (padrão: o de saída, prefixo `gravacoes/`)
  LEXIS_BUCKET_REFERENCIA / LEXIS_CHAVE_GOLDEN   base de referência (CSV) no S3
  LEXIS_KMS_KEY_ID          chave KMS para gravar objetos (opcional)
  LEXIS_MODO                replay | auto | live (padrão: auto)
  LEXIS_PROVEDOR            anthropic (padrão) | bedrock
  LEXIS_SECRET_ARN          segredo (Secrets Manager) com a chave da API Anthropic; não usado no modo bedrock
  LEXIS_AWS_REGION          região do Bedrock
Este módulo NÃO foi implantado nem testado contra a AWS real; os testes usam clientes falsos.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote_plus

from lexis.a_domain.ports import Extrator
from lexis.b_ingestion.pdf import MAX_BYTES
from lexis.c_extraction.config import Config
from lexis.d_validation.reference_base import Golden
from lexis.f_application.batch import chave_registro, processar_documento_idempotente, serializar_registro
from lexis.f_application.pipeline import Contexto, onde_falhou, registro_falha
from lexis.g_adapters import tesseract_ocr
from lexis.g_adapters.ambiente import config_do_ambiente
from lexis.g_adapters.anthropic_api import ExtratorAnthropic, chamador_anthropic
from lexis.g_adapters.log_trail import TrilhaLogsJson
from lexis.g_adapters.s3_storage import ArmazenamentoS3, ObjetoGrandeDemais

_CONTEXTO: Contexto | None = None  # reaproveitado entre invocações "quentes" da mesma instância
_SEGREDOS: dict[str, str] = {}  # ARN -> valor; evita uma chamada ao Secrets Manager por invocação


class ConfiguracaoInvalida(Exception):
    pass


def _obrigatoria(env: Mapping[str, str], nome: str) -> str:
    valor = env.get(nome)
    if not valor:
        raise ConfiguracaoInvalida(f"variável de ambiente ausente: {nome}")
    return valor


def _chave_api_do_secrets_manager(arn: str, cliente: Any | None = None) -> str:
    if arn in _SEGREDOS:
        return _SEGREDOS[arn]
    if cliente is None:
        import boto3

        cliente = boto3.client("secretsmanager")
    valor: str = cliente.get_secret_value(SecretId=arn)["SecretString"]
    _SEGREDOS[arn] = valor
    return valor


def _fabrica_extrator(env: Mapping[str, str], cfg: Config) -> Extrator:
    if env.get("LEXIS_PROVEDOR", "anthropic") == "bedrock":
        import anthropic

        # autenticação por IAM da função; o ID do modelo no Bedrock é diferente: defina LEXIS_MODEL
        cliente = anthropic.AnthropicBedrock(aws_region=env.get("LEXIS_AWS_REGION"),
                                             timeout=cfg.timeout_s, max_retries=cfg.max_retries)
        return ExtratorAnthropic(cfg, cliente=cliente)
    arn = env.get("LEXIS_SECRET_ARN")
    chave = _chave_api_do_secrets_manager(arn) if arn else cfg.api_key
    return ExtratorAnthropic(Config(**{**cfg.__dict__, "api_key": chave}))


def construir_contexto(env: Mapping[str, str], s3: Any) -> Contexto:
    cfg = config_do_ambiente(env)
    kms = env.get("LEXIS_KMS_KEY_ID")
    saida_bucket = _obrigatoria(env, "LEXIS_BUCKET_SAIDA")
    gravacoes = ArmazenamentoS3(env.get("LEXIS_BUCKET_GRAVACOES", saida_bucket), "gravacoes/", cliente=s3,
                                kms_key_id=kms)
    referencia = ArmazenamentoS3(_obrigatoria(env, "LEXIS_BUCKET_REFERENCIA"), cliente=s3)
    bruto = referencia.ler(_obrigatoria(env, "LEXIS_CHAVE_GOLDEN"))
    if bruto is None:
        raise ConfiguracaoInvalida("base de referência não encontrada no S3")
    modo = env.get("LEXIS_MODO", "auto")
    return Contexto(
        golden=Golden.de_bytes(bruto), modo=modo, cfg=cfg, gravacoes=gravacoes,
        cliente_factory=(lambda: _fabrica_extrator(env, cfg)) if modo != "replay" else None,
        chamador_factory=chamador_anthropic, leitor_ocr=tesseract_ocr.ler,
    )


def _registros_s3(evento: Mapping[str, Any]) -> list[tuple[dict[str, Any], str | None]]:
    """(registro S3, id da mensagem SQS ou None). Aceita evento S3 direto ou SQS com evento S3 no corpo."""
    saida: list[tuple[dict[str, Any], str | None]] = []
    for rec in evento.get("Records", []):
        if rec.get("eventSource") == "aws:sqs":
            corpo = json.loads(rec["body"])
            saida += [(r, str(rec["messageId"])) for r in corpo.get("Records", [])]
        else:
            saida.append((rec, None))
    return saida


def handler(
    evento: Mapping[str, Any], _contexto_lambda: Any = None, *,
    env: Mapping[str, str] | None = None, s3: Any | None = None, contexto: Contexto | None = None,
) -> dict[str, Any]:
    global _CONTEXTO
    ambiente = os.environ if env is None else env
    if s3 is None:
        import boto3

        s3 = boto3.client("s3")
    ctx = contexto or _CONTEXTO
    if ctx is None:
        ctx = _CONTEXTO = construir_contexto(ambiente, s3)
    ctx.reiniciar()  # o orçamento de tokens vale por invocação, não por instância quente

    bucket_entrada = _obrigatoria(ambiente, "LEXIS_BUCKET_ENTRADA")
    bucket_saida = _obrigatoria(ambiente, "LEXIS_BUCKET_SAIDA")
    if bucket_entrada == bucket_saida:  # a gravação do resultado dispararia um novo evento (laço) e sobrescreveria
        raise ConfiguracaoInvalida("LEXIS_BUCKET_SAIDA deve ser diferente de LEXIS_BUCKET_ENTRADA")
    kms = ambiente.get("LEXIS_KMS_KEY_ID")
    entrada = ArmazenamentoS3(bucket_entrada, cliente=s3, limite_bytes=MAX_BYTES)
    destino = ArmazenamentoS3(bucket_saida, cliente=s3, kms_key_id=kms)
    trilha = TrilhaLogsJson()
    run_id = str(getattr(_contexto_lambda, "aws_request_id", None) or uuid.uuid4().hex[:12])
    resumo: list[dict[str, str]] = []
    falhas_sqs: list[dict[str, str]] = []

    for rec, id_msg in _registros_s3(evento):
        bucket = rec["s3"]["bucket"]["name"]
        chave = unquote_plus(rec["s3"]["object"]["key"])
        if bucket != bucket_entrada:  # nunca processa objetos de buckets não configurados
            trilha.registrar({"evento": "evento_rejeitado", "motivo": "bucket_inesperado"})
            continue
        if not chave.lower().endswith(".pdf"):
            trilha.registrar({"evento": "evento_rejeitado", "motivo": "extensao_nao_pdf"})
            continue
        try:
            conteudo = entrada.ler(chave)
            if conteudo is None:
                raise FileNotFoundError(chave)
            reg, disposicao = processar_documento_idempotente(
                chave, conteudo, destino, ctx, run_id, propagar_transitorios=True)
        except ObjetoGrandeDemais as e:
            reg = registro_falha(run_id, chave, None, "ARQUIVO_GRANDE_DEMAIS", f"{e.tamanho} bytes", ctx.versoes())
            destino.gravar(chave_registro(chave), serializar_registro(reg))
            disposicao = "PROCESSADO"
        except Exception as e:
            # falha transitória (S3 em throttling, provedor fora, erro inesperado): NÃO vira resultado final.
            # Devolve à fila (reentrega e, esgotadas as tentativas, DLQ). Registra onde, sem texto do documento.
            trilha.registrar({"evento": "falha_transitoria", "arquivo": chave, "tipo": type(e).__name__,
                              "onde": onde_falhou(e)})
            if id_msg is None:
                raise
            falhas_sqs.append({"itemIdentifier": id_msg})
            continue
        trilha.registrar({
            "evento": "doc_concluido", "arquivo": chave, "sha256": reg.documento.get("sha256"),
            "disposicao": disposicao, "decisao": reg.decisao.estado.value,
            "tokens": (reg.auditoria.get("tokens_entrada") or 0) + (reg.auditoria.get("tokens_saida") or 0),
            "custo_estimado_usd": reg.auditoria.get("custo_estimado_usd"),
        })
        resumo.append({"arquivo": chave, "decisao": reg.decisao.estado.value, "disposicao": disposicao})
    return {"processados": resumo, "batchItemFailures": falhas_sqs}
