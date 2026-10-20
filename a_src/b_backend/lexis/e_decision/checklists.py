"""Fichas de conferência: para cada exceção, o que conferir, onde e qual ação tomar."""

from __future__ import annotations

from lexis.a_domain.models import CampoSaida, Ficha, RegraResultado, Severidade, TipoAcao
from lexis.a_domain.specs import SPECS

ACAO_POR_REGRA: dict[str, TipoAcao] = {
    "GOLDEN_NAO_ENCONTRADO": TipoAcao.CADASTRAR_EMISSOR,
    "GOLDEN_DIVERGENTE": TipoAcao.RESOLVER_INCONSISTENCIA,
    "GOLDEN_AMBIGUO": TipoAcao.RESOLVER_INCONSISTENCIA,
    "GOLDEN_INATIVO": TipoAcao.RESOLVER_INCONSISTENCIA,
    "CLASSIFICACAO_DIVERGENTE": TipoAcao.CONFERIR_CLASSIFICACAO,
    "TITULO_DIVERGE_CORPO": TipoAcao.CONFERIR_CLASSIFICACAO,
    "TIPO_NAO_SUPORTADO": TipoAcao.CONFERIR_CLASSIFICACAO,
    "CAMPO_PENDENTE_NO_AVISO": TipoAcao.AGUARDAR_AVISO_COMPLEMENTAR,
    "EVIDENCIA_NAO_ENCONTRADA": TipoAcao.CORRIGIR_EXTRACAO,
    "VALOR_NAO_INTERPRETAVEL": TipoAcao.CORRIGIR_EXTRACAO,
    "CAMPO_OBRIGATORIO_AUSENTE": TipoAcao.CORRIGIR_EXTRACAO,
    "SCAN_LEITURAS_DIVERGEM": TipoAcao.CORRIGIR_EXTRACAO,
    "OCR_NAO_CORROBORA": TipoAcao.CORRIGIR_EXTRACAO,
    "IDENTIFICADOR_NAO_EXTRAIDO": TipoAcao.CORRIGIR_EXTRACAO,
    "INJECAO_SUSPEITA": TipoAcao.VERIFICAR_SEGURANCA,
    "TEXTO_OCULTO": TipoAcao.VERIFICAR_SEGURANCA,
    "CONTEUDO_ATIVO_PDF": TipoAcao.VERIFICAR_SEGURANCA,
    "OCR_INDISPONIVEL": TipoAcao.CORRIGIR_EXTRACAO,
    "DUPLICATA_POSSIVEL": TipoAcao.RESOLVER_INCONSISTENCIA,
    "MODELO_NAO_AVALIADO": TipoAcao.CORRIGIR_EXTRACAO,
}

# Texto próprio quando a ação genérica do tipo não descreve o que o operador deve fazer.
TEXTO_POR_REGRA: dict[str, str] = {
    "OCR_INDISPONIVEL": "Scan lido só pelo modelo de visão (sem leitor independente): conferir na imagem da página "
                        "todos os campos extraídos, em especial datas, valores e identificadores.",
    "DUPLICATA_POSSIVEL": "Comparar com o outro documento do mesmo evento: é reenvio, retificação ou outro evento? "
                          "Aprovar só um registro por evento.",
    "MODELO_NAO_AVALIADO": "A leitura veio de um modelo de fallback, não avaliado: conferir todos os campos no "
                           "documento ou reprocessar com o modelo avaliado.",
}

ACAO_TEXTO: dict[TipoAcao, str] = {
    TipoAcao.CADASTRAR_EMISSOR: "Confirmar o emissor na fonte oficial (CVM/B3) e cadastrá-lo na base de referência antes de processar o evento.",
    TipoAcao.RESOLVER_INCONSISTENCIA: "Comparar os valores com o documento original e com o emissor; corrigir o dado errado ou solicitar retificação.",
    TipoAcao.CONFERIR_CLASSIFICACAO: "Conferir no corpo do aviso qual é o tipo real do evento (muda o tratamento tributário).",
    TipoAcao.AGUARDAR_AVISO_COMPLEMENTAR: "Aguardar o aviso complementar do emissor; reprocessar quando divulgado.",
    TipoAcao.CORRIGIR_EXTRACAO: "Conferir o campo no documento e corrigir o valor extraído.",
    TipoAcao.VERIFICAR_SEGURANCA: "Inspecionar o arquivo antes de confiar no registro (conteúdo suspeito ou oculto).",
    TipoAcao.REPROCESSAR: "Reprocessar o documento; se persistir, tratar manualmente.",
}


def montar_fichas(regras: list[RegraResultado], campos: dict[str, CampoSaida]) -> list[Ficha]:
    fichas: list[Ficha] = []
    for r in regras:
        gera_ficha = r.id == "CAMPO_PENDENTE_NO_AVISO" or (
            r.id == "OCR_INDISPONIVEL" and bool(SPECS.politica["revisao_scan_sem_ocr_independente"])
        )
        if r.resultado != "FALHA" or r.severidade is Severidade.INFO and not gera_ficha:
            continue
        acao = ACAO_POR_REGRA.get(r.id, TipoAcao.RESOLVER_INCONSISTENCIA)
        alvo = next((campos[c] for c in r.campos if c in campos and campos[c].evidencia), None)
        fichas.append(Ficha(
            campo=r.campos[0] if r.campos else None, codigo=r.id, tipo_acao=acao,
            acao_sugerida=TEXTO_POR_REGRA.get(r.id, ACAO_TEXTO[acao]), esperado=r.esperado, observado=r.observado or r.detalhe,
            onde_conferir=alvo.evidencia if alvo else None,
        ))
    return fichas
