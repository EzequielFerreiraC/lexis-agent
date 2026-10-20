"""Base de referência: consulta exata por ISIN/ticker/CNPJ. Nome só gera sugestão, nunca confirma."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from difflib import SequenceMatcher

from lexis.a_domain.models import ValidacaoGolden
from lexis.a_domain.normalization import nome_emissor_canonico
from lexis.a_domain.specs import SPECS


@dataclass(frozen=True)
class RegistroGolden:
    emissor: str
    cnpj: str
    isin: str
    ticker: str
    classe: str
    segmento_listagem: str
    status: str

    def como_dict(self) -> dict[str, str]:
        return {
            "emissor": self.emissor, "cnpj": self.cnpj, "isin": self.isin, "ticker": self.ticker,
            "classe": self.classe, "segmento_listagem": self.segmento_listagem, "status": self.status,
        }


class Golden:
    def __init__(self, registros: list[RegistroGolden], sha: str) -> None:
        self.registros = registros
        self.sha = sha
        self._isin = {r.isin: r for r in registros}
        self._ticker = {r.ticker: r for r in registros}
        # um CNPJ tem uma linha por classe (ON, PN, unit): o CNPJ confirma o emissor, não a classe
        self._cnpj: dict[str, list[RegistroGolden]] = {}
        for r in registros:
            self._cnpj.setdefault(r.cnpj, []).append(r)

    @classmethod
    def de_bytes(cls, bruto: bytes) -> Golden:
        """Constrói a base a partir do CSV em memória (arquivo local, objeto S3, etc.)."""
        linhas = csv.DictReader(bruto.decode("utf-8").splitlines())
        regs = [
            RegistroGolden(
                emissor=(r["emissor"] or "").strip(), cnpj=(r["cnpj"] or "").strip(),
                isin=(r["isin"] or "").strip().upper(), ticker=(r["ticker"] or "").strip().upper(),
                classe=(r["classe"] or "").strip().upper(),
                segmento_listagem=(r["segmento_listagem"] or "").strip(),
                status=(r["status"] or "").strip().lower(),
            )
            for r in linhas
        ]
        return cls(regs, hashlib.sha256(bruto).hexdigest())

    def consultar(
        self, *, isin: str | None, ticker: str | None, cnpj: str | None,
        emissor: str | None, classe: str | None,
    ) -> ValidacaoGolden:
        achados: dict[str, RegistroGolden] = {}
        if isin and isin in self._isin:
            achados["isin"] = self._isin[isin]
        if ticker and ticker in self._ticker:
            achados["ticker"] = self._ticker[ticker]
        if cnpj and cnpj in self._cnpj:
            candidatos = self._cnpj[cnpj]
            ja = {r.isin for r in achados.values()}
            mesma_classe = [r for r in candidatos if r.isin in ja]
            if mesma_classe:
                achados["cnpj"] = mesma_classe[0]
            elif len(candidatos) == 1 or achados:
                # CNPJ de outro emissor (ou de uma classe que ISIN/ticker não confirmam): vira AMBIGUOUS abaixo
                achados["cnpj"] = candidatos[0]
            else:
                return ValidacaoGolden(
                    status="AMBIGUOUS",
                    comparacoes=[
                        {"campo": "cnpj", "aviso": cnpj, "golden": f"{r.emissor} ({r.ticker})",
                         "resultado": "APONTA_PARA_OUTRO_REGISTRO"}
                        for r in candidatos
                    ],
                )

        if not achados:
            return ValidacaoGolden(
                status="NOT_FOUND", sugestao_por_nome=self._sugerir(emissor),
                comparacoes=[
                    {"campo": c, "aviso": v, "golden": None, "resultado": "NAO_ENCONTRADO"}
                    for c, v in (("isin", isin), ("ticker", ticker), ("cnpj", cnpj)) if v
                ],
            )

        distintos = {r.isin for r in achados.values()}
        if len(distintos) > 1:
            return ValidacaoGolden(
                status="AMBIGUOUS",
                comparacoes=[
                    {"campo": c, "aviso": getattr(r, c), "golden": r.emissor, "resultado": "APONTA_PARA_OUTRO_REGISTRO"}
                    for c, r in achados.items()
                ],
            )

        reg = next(iter(achados.values()))
        comparacoes: list[dict[str, object]] = []
        divergiu = False

        def comparar(campo: str, aviso: str | None, golden: str, canon: bool = False) -> None:
            nonlocal divergiu
            if not aviso:
                comparacoes.append({"campo": campo, "aviso": None, "golden": golden, "resultado": "NAO_INFORMADO"})
                return
            ok = (
                nome_emissor_canonico(aviso) == nome_emissor_canonico(golden)
                if canon else aviso == golden
            )
            divergiu = divergiu or not ok
            comparacoes.append({
                "campo": campo, "aviso": aviso, "golden": golden,
                "resultado": "IGUAL" if ok else "DIVERGE",
            })

        comparar("isin", isin, reg.isin)
        comparar("ticker", ticker, reg.ticker)
        comparar("cnpj", cnpj, reg.cnpj)
        comparar("emissor", emissor, reg.emissor, canon=True)
        comparar("classe_acao", classe, reg.classe)
        comparacoes.append({
            "campo": "status", "aviso": None, "golden": reg.status,
            "resultado": "ATIVO" if reg.status == "ativo" else "INATIVO",
        })
        return ValidacaoGolden(
            status="PARTIAL_MISMATCH" if divergiu else "MATCH",
            registro_golden=reg.como_dict(), comparacoes=comparacoes,
        )

    def _sugerir(self, emissor: str | None) -> dict[str, object] | None:
        if not emissor:
            return None
        alvo = nome_emissor_canonico(emissor)
        melhor = max(
            self.registros,
            key=lambda r: SequenceMatcher(None, alvo, nome_emissor_canonico(r.emissor)).ratio(),
        )
        score = SequenceMatcher(None, alvo, nome_emissor_canonico(melhor.emissor)).ratio()
        if score < float(SPECS.politica["limiar_nome_sugestao"]):
            return None
        return {
            "emissor": melhor.emissor, "ticker": melhor.ticker, "similaridade": round(score, 2),
            "uso": "apenas dica para o operador; nome parecido não confirma identidade",
        }
