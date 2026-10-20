"""Tools de validação (somente leitura) + orquestrador + function calling com o modelo.

Fluxo (loop real de function calling):
  1. o orquestrador oferece ao modelo o registro já normalizado e SÓ as tools aplicáveis ao tipo;
  2. o modelo pede as tools; cada pedido passa por `atender`, que aplica a allow-list e exige argumentos IGUAIS
     aos campos já extraídos (o modelo não consegue validar valores inventados);
  3. o resultado volta ao modelo como `tool_result` (ou erro, para ele corrigir), até ele encerrar com um parecer;
  4. o orquestrador executa as tools obrigatórias que o modelo não pediu (rede de segurança);
  5. o veredito é sempre o RESULTADO da tool (código), nunca o texto do modelo; o parecer é só informativo.

Quem conversa com o modelo é um `ChamadorDeTools` injetado (adaptador em `g_adapters/anthropic_api.py`);
este módulo não faz chamada de rede.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from lexis.a_domain.models import RegraResultado, TipoEvento, ValidacaoGolden
from lexis.a_domain.normalization import Proporcao
from lexis.a_domain.ports import ChamadorDeTools, ConversaTools, ErroExtracao, PedidoTools
from lexis.d_validation import coherence as rules
from lexis.d_validation.reference_base import Golden


def _tool(nome: str, desc: str, campos: tuple[str, ...]) -> dict[str, Any]:
    """strict: o provedor garante JSON válido contra o schema. Campos ausentes do registro são OMITIDOS (string
    opcional, sem `null`): o modo strict limita parâmetros anuláveis (16) e opcionais (24) por requisição, e as
    4 tools somam no máximo 18 opcionais. Só `tipo_evento` é obrigatório (está sempre no registro)."""
    return {"name": nome, "description": desc, "strict": True,
            "input_schema": {"type": "object", "properties": {k: {"type": "string"} for k in campos},
                             "required": [k for k in campos if k == "tipo_evento"], "additionalProperties": False}}


DEFINICOES: dict[str, dict[str, Any]] = {
    "consultar_golden": _tool(
        "consultar_golden", "Consulta a base de referência por ISIN, ticker e CNPJ e compara emissor e classe.",
        ("isin", "ticker", "cnpj", "emissor", "classe_acao")),
    "checar_datas": _tool(
        "checar_datas", "Verifica a coerência entre as datas do evento (ISO 8601).",
        ("tipo_evento", "data_aprovacao", "data_com", "data_ex", "data_pagamento", "data_credito_ativos")),
    "checar_tributacao": _tool(
        "checar_tributacao", "Verifica valores monetários e a relação bruto × (1 − alíquota) = líquido.",
        ("tipo_evento", "valor_bruto", "aliquota_irrf", "valor_liquido", "custo_atribuido")),
    "checar_proporcao": _tool(
        "checar_proporcao", "Verifica a proporção de grupamento, desdobramento ou bonificação.",
        ("tipo_evento", "termo_a", "termo_b", "percentual_declarado", "forma")),
}

Dados = dict[str, Any]


def tools_aplicaveis(tipo: TipoEvento, dados: Dados) -> list[str]:
    nomes = ["consultar_golden", "checar_datas"]
    if tipo in (TipoEvento.DIVIDENDO, TipoEvento.JCP) or any(
        c in dados for c in ("valor_bruto", "valor_liquido", "aliquota_irrf", "custo_atribuido")
    ):
        nomes.append("checar_tributacao")
    if tipo in (TipoEvento.GRUPAMENTO, TipoEvento.DESDOBRAMENTO, TipoEvento.BONIFICACAO) or "proporcao" in dados:
        nomes.append("checar_proporcao")
    return nomes


def args_esperados(nome: str, tipo: TipoEvento, dados: Dados) -> dict[str, str]:
    def s(c: str) -> str | None:
        v = dados.get(c)
        if v is None:
            return None
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, Decimal):
            return format(v, "f")
        return str(v)

    if nome == "consultar_golden":
        campos = ("isin", "ticker", "cnpj", "emissor", "classe_acao")
        base = {c: s(c) for c in campos}
    elif nome == "checar_datas":
        base = {c: s(c) for c in ("data_aprovacao", "data_com", "data_ex", "data_pagamento", "data_credito_ativos")}
        base["tipo_evento"] = tipo.value
    elif nome == "checar_tributacao":
        base = {c: s(c) for c in ("valor_bruto", "aliquota_irrf", "valor_liquido", "custo_atribuido")}
        base["tipo_evento"] = tipo.value
    else:
        p = dados.get("proporcao")
        base = {"tipo_evento": tipo.value}
        if isinstance(p, Proporcao):
            base.update(termo_a=str(p.termo_a), termo_b=str(p.termo_b), forma=p.forma)
            if p.percentual is not None:
                base["percentual_declarado"] = format(p.percentual, "f")
    # Na ORDEM do schema: em modo strict o modelo só emite propriedades nessa ordem; se o registro mostrar outra,
    # ele copia na ordem vista e, passado um campo, não consegue mais voltar para o anterior (omite-o).
    return {k: v for k in DEFINICOES[nome]["input_schema"]["properties"] if (v := base.get(k))}


def _dados_de_args(args: dict[str, str]) -> Dados:
    d: Dados = {}
    for k, v in args.items():
        if k.startswith("data_"):
            d[k] = date.fromisoformat(v)
        elif k in {"valor_bruto", "aliquota_irrf", "valor_liquido", "custo_atribuido"}:
            d[k] = Decimal(v)
        elif k not in {"tipo_evento", "termo_a", "termo_b", "percentual_declarado", "forma"}:
            d[k] = v
    if "termo_a" in args:
        pct = Decimal(args["percentual_declarado"]) if "percentual_declarado" in args else None
        d["proporcao"] = Proporcao(int(args["termo_a"]), int(args["termo_b"]), pct, args.get("forma", "RAZAO"))
    return d


@dataclass
class ResultadoTool:
    nome: str
    regras: list[RegraResultado]
    golden: ValidacaoGolden | None = None


def executar_tool(nome: str, args: dict[str, str], golden: Golden) -> ResultadoTool:
    """Executa uma tool da allow-list. Qualquer outro nome é rejeitado."""
    if nome not in DEFINICOES:
        raise KeyError(f"tool fora da allow-list: {nome}")
    tipo = TipoEvento(args.get("tipo_evento", TipoEvento.OUTRO.value))
    dados = _dados_de_args(args)
    if nome == "consultar_golden":
        v = golden.consultar(
            isin=args.get("isin"), ticker=args.get("ticker"), cnpj=args.get("cnpj"),
            emissor=args.get("emissor"), classe=args.get("classe_acao"),
        )
        return ResultadoTool(nome, rules.checar_golden(v), v)
    if nome == "checar_datas":
        return ResultadoTool(nome, rules.checar_datas(tipo, dados))
    if nome == "checar_tributacao":
        return ResultadoTool(nome, rules.checar_tributacao(tipo, dados))
    return ResultadoTool(nome, rules.checar_proporcao(tipo, dados))


def resultado_para_modelo(r: ResultadoTool) -> dict[str, Any]:
    """Conteúdo do tool_result: só tipos JSON nativos (comparável com a gravação após ida e volta)."""
    out: dict[str, Any] = {"regras": [
        {"id": x.id, "resultado": x.resultado, "severidade": x.severidade.value,
         "esperado": x.esperado, "observado": x.observado} for x in r.regras]}
    if r.golden is not None:
        out["golden"] = r.golden.status
    return out


@dataclass
class Validacoes:
    regras: list[RegraResultado] = field(default_factory=list)
    golden: ValidacaoGolden | None = None
    chamadas: list[dict[str, Any]] = field(default_factory=list)
    conversa: ConversaTools | None = None


def orquestrar(
    tipo: TipoEvento, dados: Dados, golden: Golden, chamador: ChamadorDeTools | None,
) -> Validacoes:
    obrigatorias = tools_aplicaveis(tipo, dados)
    esperados = {n: args_esperados(n, tipo, dados) for n in obrigatorias}
    out = Validacoes()
    executadas: set[str] = set()

    def atender(nome: str, args: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Uma chamada pedida pelo modelo: rejeita (com motivo, para ele corrigir) ou executa de verdade."""
        limpo = {k: str(v) for k, v in args.items() if v not in (None, "")}
        motivo = None
        if nome not in DEFINICOES:
            motivo = "FORA_DA_ALLOW_LIST"
        elif nome not in esperados:
            motivo = "NAO_APLICAVEL_AO_TIPO"
        elif nome in executadas:
            motivo = "DUPLICADA"
        elif limpo != esperados[nome]:
            motivo = "ARGS_DIVERGEM_DO_EXTRAIDO"
        if motivo is not None:
            rejeicao: dict[str, Any] = {"tool": nome, "origem": "MODELO", "aceita": False, "motivo": motivo}
            erro: dict[str, Any] = {"erro": motivo}
            if motivo == "ARGS_DIVERGEM_DO_EXTRAIDO":
                rejeicao["args_recebidos"] = limpo
                # diz ONDE divergiu (nomes de campo), não o valor certo: o modelo tem o registro para recopiar
                erro["campos_divergentes"] = sorted(
                    k for k in set(limpo) | set(esperados[nome]) if limpo.get(k) != esperados[nome].get(k))
            out.chamadas.append(rejeicao)
            return erro, True
        r = executar_tool(nome, esperados[nome], golden)
        _registrar(out, r, esperados[nome], "MODELO")
        executadas.add(nome)
        return resultado_para_modelo(r), False

    if chamador is not None:
        resumo = {k: v for n in obrigatorias for k, v in esperados[n].items()}
        pedido = PedidoTools(tipo=tipo, registro=resumo, ferramentas=[DEFINICOES[n] for n in obrigatorias])
        falha: str | None = None
        try:
            out.conversa = chamador.conduzir(pedido, atender)
            if out.conversa.encerramento and out.conversa.encerramento.startswith("ERRO:"):
                falha = out.conversa.encerramento.removeprefix("ERRO:")
        except ErroExtracao as e:  # gravação ausente em replay, sem chamador etc.: a validação segue sem o modelo
            falha = e.codigo
        except Exception as e:  # falha do provedor não derruba a validação
            falha = f"FALHA_PROVEDOR:{type(e).__name__}"
        if falha:
            out.chamadas.append({"tool": None, "origem": "MODELO", "aceita": False, "motivo": falha})

    for nome in obrigatorias:
        if nome not in executadas:
            _registrar(out, executar_tool(nome, esperados[nome], golden), esperados[nome], "ORQUESTRADOR")
    return out


def _registrar(out: Validacoes, r: ResultadoTool, args: dict[str, str], origem: str) -> None:
    out.regras += r.regras
    if r.golden is not None:
        out.golden = r.golden
    out.chamadas.append({
        "tool": r.nome, "origem": origem, "aceita": True, "argumentos": args,
        "resultado": {"regras_ok": sum(x.resultado == "OK" for x in r.regras),
                      "regras_falha": [x.id for x in r.regras if x.resultado == "FALHA"]},
    })

