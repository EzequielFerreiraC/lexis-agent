"""Verificação de integridade de uma execução: a trilha, os registros e as decisões humanas ainda são os gravados?

Opera sobre a porta de armazenamento (pasta local ou S3), sem I/O próprio. Confere:
  1. a cadeia de hashes de `auditoria.jsonl` (linha alterada, removida ou fora de ordem);
  2. cada `json/<documento>.json` contra o sha256 selado no evento `registros_publicados` (e arquivos a mais);
  3. `revisoes.jsonl`: a própria cadeia, se cada decisão humana aponta para o registro como ele está, e se cada uma
     tem o seu evento `revisao_humana` na trilha (e vice-versa).
Detecta adulteração; não a impede (quem reescreve tudo pode recalcular os hashes). Ver e_docs/f_governance.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from lexis.a_domain.hash_chain import sem_selo, verificar_cadeia
from lexis.a_domain.ports import ArmazenamentoObjetos
from lexis.f_application.batch import chave_registro

TRILHA = "auditoria.jsonl"
REVISOES = "revisoes.jsonl"


@dataclass
class Verificacao:
    nome: str
    problemas: list[str] = field(default_factory=list)
    nota: str = ""

    @property
    def ok(self) -> bool:
        return not self.problemas


def _sha(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def _eventos(linhas: list[str]) -> list[dict[str, Any]]:
    saida: list[dict[str, Any]] = []
    for linha in linhas:
        try:
            evento = json.loads(linha)
        except json.JSONDecodeError:
            continue  # a verificação da cadeia já acusa a linha inválida
        if isinstance(evento, dict):
            saida.append(evento)
    return saida


def verificar_integridade(armazem: ArmazenamentoObjetos) -> list[Verificacao]:
    bruto = armazem.ler(TRILHA)
    if bruto is None:
        return [Verificacao("Cadeia da trilha", [f"{TRILHA} ausente"])]
    linhas = [x for x in bruto.decode("utf-8").splitlines() if x.strip()]
    eventos = _eventos(linhas)
    resultado = [Verificacao("Cadeia da trilha", verificar_cadeia(linhas), f"{len(linhas)} eventos")]
    resultado.append(_verificar_registros(armazem, eventos))
    resultado.append(_verificar_revisoes(armazem, eventos))
    return resultado


def _publicados(eventos: list[dict[str, Any]]) -> dict[str, str] | None:
    selos = [e for e in eventos if e.get("evento") == "registros_publicados"]
    return dict(selos[-1].get("registros") or {}) if selos else None


def _verificar_registros(armazem: ArmazenamentoObjetos, eventos: list[dict[str, Any]]) -> Verificacao:
    v = Verificacao("Registros contra o selo da trilha")
    publicados = _publicados(eventos)
    if publicados is None:
        v.problemas.append("a trilha não tem o evento registros_publicados (execução anterior ao selo?)")
        return v
    for chave, esperado in sorted(publicados.items()):
        atual = armazem.ler(chave)
        if atual is None:
            v.problemas.append(f"{chave}: ausente")
        elif _sha(atual) != esperado:
            v.problemas.append(f"{chave}: alterado depois de gravado (sha256 não confere)")
    for chave in armazem.listar("json/"):
        if chave.endswith(".json") and chave not in publicados:
            v.problemas.append(f"{chave}: não consta do selo da trilha")
    v.nota = f"{len(publicados)} registros"
    return v


def _verificar_revisoes(armazem: ArmazenamentoObjetos, eventos: list[dict[str, Any]]) -> Verificacao:
    v = Verificacao("Decisões do operador")
    bruto = armazem.ler(REVISOES)
    na_trilha = {str(e.get("sha256_revisao")) for e in eventos if e.get("evento") == "revisao_humana"}
    if bruto is None:
        if na_trilha:
            v.problemas.append(f"a trilha registra {len(na_trilha)} decisão(ões), mas {REVISOES} não existe")
        v.nota = "nenhuma decisão registrada"
        return v
    linhas = [x for x in bruto.decode("utf-8").splitlines() if x.strip()]
    v.problemas += [f"{REVISOES} {p}" for p in verificar_cadeia(linhas)]
    publicados = _publicados(eventos) or {}
    vistos: set[str] = set()
    for revisao in _eventos(linhas):
        arquivo = str(revisao.get("arquivo"))
        chave = chave_registro(arquivo)
        atual = armazem.ler(chave)
        if atual is None or _sha(atual) != revisao.get("sha256_registro"):
            v.problemas.append(f"{arquivo}: a decisão humana não corresponde ao registro atual")
        elif chave in publicados and publicados[chave] != revisao.get("sha256_registro"):
            v.problemas.append(f"{arquivo}: a decisão humana foi tomada sobre outro conteúdo")
        sha_linha = _sha(json.dumps(sem_selo(revisao), ensure_ascii=False).encode("utf-8"))
        vistos.add(sha_linha)
        if sha_linha not in na_trilha:
            v.problemas.append(f"{arquivo}: decisão sem o evento revisao_humana correspondente na trilha")
    if sobra := na_trilha - vistos:
        v.problemas.append(f"{len(sobra)} evento(s) revisao_humana na trilha sem a decisão em {REVISOES}")
    v.nota = f"{len(linhas)} decisão(ões)"
    return v
