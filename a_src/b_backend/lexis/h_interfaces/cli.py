"""Linha de comando: `python -m lexis run ...`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from lexis.a_domain.ports import ErroExtracao
from lexis.f_application.report import publicar_relatorios
from lexis.g_adapters.ambiente import config_do_ambiente
from lexis.g_adapters.local_execution import contexto_local, executar_lote
from lexis.g_adapters.local_storage import ArmazenamentoLocal
from lexis.g_adapters.log_trail import configurar_log
from lexis.g_adapters.report_folder import nova_pasta_relatorio

if TYPE_CHECKING:
    from sqlalchemy import Engine

PADRAO_ENTRADA = Path("f_data/a_input")
PADRAO_GOLDEN = Path("f_data/c_golden_records/golden_records.csv")
PADRAO_SAIDA = Path("f_data/b_output")
PADRAO_REPLAY = Path("c_replay")
PADRAO_EXECUCOES = PADRAO_SAIDA  # a tela também grava em f_data/b_output/report_yymmdd_hhmm
PADRAO_FRONT = Path("a_src/a_frontend/dist")


def _run(a: argparse.Namespace) -> int:
    ctx = contexto_local(a.golden, a.modo, config_do_ambiente(), a.replay, usar_ocr=not a.sem_ocr)
    pasta = nova_pasta_relatorio(a.saida)
    try:
        resultados, run_id = executar_lote(a.entrada, pasta, ctx, forcar=a.forcar, cache=a.saida / "_cache")
    except ErroExtracao as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    publicar_relatorios(ArmazenamentoLocal(pasta), resultados, run_id)
    for nome, reg, disp in resultados:
        print(f"{nome:<45} {reg.decisao.estado.value:<20} {disp}")
    print(f"\nSaída em {pasta}/ (json/, relatorio_excecoes.md, resumo_execucao.json, auditoria.jsonl)")
    if os.environ.get("LEXIS_DB_URL"):  # com banco configurado, a execução também vira projeção consultável
        return _importar_pastas([pasta])
    return 0


# ----------------------------------------------------------------------- banco (LEXIS_DB_URL)


def _engine() -> Engine | None:
    from sqlalchemy.exc import SQLAlchemyError

    from lexis.g_adapters.sql_store import conectar

    url = os.environ.get("LEXIS_DB_URL")
    if not url:
        print("erro: defina LEXIS_DB_URL (ex.: mysql+pymysql://lexis:<senha>@127.0.0.1:3306/lexis)", file=sys.stderr)
        return None
    try:
        return conectar(url)
    except ImportError:
        print("erro: dependências do banco ausentes. Instale com: pip install -e '.[db]'", file=sys.stderr)
    except SQLAlchemyError as e:  # sem a mensagem: pode trazer a URL com a senha
        print(f"erro: não consegui conectar ao banco ({type(e).__name__})", file=sys.stderr)
    return None


def pasta_de_registros(pasta: Path) -> Path:
    """A CLI grava em <pasta>/json; o console, em <pasta>/saida/json (com revisoes.jsonl ao lado)."""
    return pasta / "saida" if (pasta / "saida" / "json").is_dir() else pasta


def _importar_pastas(pastas: list[Path]) -> int:
    from lexis.g_adapters.sql_store import ler_revisoes, projetar_execucao

    engine = _engine()
    if engine is None:
        return 2
    for pasta in pastas:
        base = pasta_de_registros(pasta)
        if not (base / "json").is_dir():
            print(f"erro: {pasta} não tem json/ (não é uma pasta de execução)", file=sys.stderr)
            return 2
        armazem = ArmazenamentoLocal(base)
        r = projetar_execucao(engine, pasta.name, armazem, ler_revisoes(armazem.ler("revisoes.jsonl")))
        print(f"banco: {r.execucao_id}: {r.documentos} documento(s), {r.revisoes} revisão(ões) nova(s)")
    return 0


def _db_importar(a: argparse.Namespace) -> int:
    return _importar_pastas(a.pastas)


def _auditoria(a: argparse.Namespace) -> int:
    import json
    import secrets

    from lexis.g_adapters import sql_store

    engine = _engine()
    if engine is None:
        return 2
    try:
        if a.acao == "sortear":
            semente = a.semente or secrets.token_hex(8)
            ids = sql_store.sortear_auditoria(engine, a.taxa, semente)
            print(f"{len(ids)} documento(s) sorteado(s) para auditoria (semente {semente})")
        elif a.acao == "pendentes":
            for p in sql_store.pendentes(engine):
                print(f"#{p['id']:<5} {p['estrato']:<18} {p['execucao_id']}/{p['arquivo']}  pagamento {p['data_pagamento']}")
        elif a.acao == "registrar":
            sql_store.registrar_veredito(engine, a.id, a.veredito, a.auditor, campo_errado=a.campo,
                                         valor_correto=a.valor, observacao=a.observacao)
            print(f"veredito {a.veredito} registrado na auditoria #{a.id}")
        else:
            print(json.dumps(sql_store.metricas(engine), ensure_ascii=False, indent=2, default=str))
    except ValueError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    return 0


def _usuario(a: argparse.Namespace) -> int:
    import getpass
    import os

    from lexis.g_adapters.sql_users import criar_usuario

    engine = _engine()
    if engine is None:
        return 2
    senha = os.environ.get("LEXIS_SENHA_NOVA")  # para automação; sem ela, pergunta sem ecoar
    if senha is None:
        senha = getpass.getpass("senha (mín. 12 caracteres): ")
        if getpass.getpass("repita a senha: ") != senha:
            print("erro: as senhas não conferem", file=sys.stderr)
            return 2
    try:
        u = criar_usuario(engine, a.email, a.nome, senha)
    except ValueError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    print(f"usuário {u.login} ({u.nome}) criado")
    return 0


def _avaliar(a: argparse.Namespace) -> int:
    from lexis.i_assessment.evaluation import avaliar_mutacoes, imprimir

    # em replay o OCR vem só da gravação (c_replay/<sha>/ocr.json), nunca do Tesseract da máquina: a avaliação mede
    # o mesmo que `run` entrega e não depende do ambiente
    ctx = contexto_local(a.golden, "replay", config_do_ambiente(), a.replay, usar_ocr=True)
    rel = avaliar_mutacoes(a.entrada, ctx)
    destino = nova_pasta_relatorio(a.saida) / "avaliacao_mutacao.json"
    imprimir(rel, destino)
    return 0 if rel.get("aprovado", True) else 1


def _auditar(a: argparse.Namespace) -> int:
    from lexis.f_application.integrity import verificar_integridade

    if not a.pasta.is_dir():
        print(f"erro: pasta não encontrada: {a.pasta}", file=sys.stderr)
        return 2
    verificacoes = verificar_integridade(ArmazenamentoLocal(a.pasta))
    for v in verificacoes:
        print(f"{'OK   ' if v.ok else 'FALHA'} {v.nome}" + (f" ({v.nota})" if v.nota else ""))
        for p in v.problemas:
            print(f"      - {p}")
    integra = all(v.ok for v in verificacoes)
    print("\nÍntegra: trilha, registros e decisões são os gravados." if integra else
          "\nNÃO íntegra: algo foi alterado, removido ou acrescentado depois de gravado.")
    return 0 if integra else 1


def _serve(a: argparse.Namespace) -> int:
    import os

    try:
        import uvicorn

        from lexis.h_interfaces.api.app import criar_app
        from lexis.h_interfaces.api.config import ConfigServidor, dominios_do_ambiente
        from lexis.h_interfaces.api.security import (
            HOST_DO_CONTAINER,
            HOSTS_PERMITIDOS,
            em_container,
            gerar_token,
            host_permitido,
        )
    except ImportError:
        print("erro: dependências web ausentes. Instale com: pip install -e '.[web]'", file=sys.stderr)
        return 2
    if a.container:
        # O Docker só encaminha a porta publicada se o processo escutar na interface do container; o
        # docker-compose.yml publica essa porta só em 127.0.0.1 do host. Token e Host continuam valendo.
        if not em_container():
            print("erro: --container só pode ser usado dentro de um container", file=sys.stderr)
            return 2
        escuta, endereco = HOST_DO_CONTAINER, "127.0.0.1"
    elif not host_permitido(a.host):  # só loopback: a API executa código e pode gastar dinheiro
        print(f"erro: --host deve ser loopback ({', '.join(sorted(HOSTS_PERMITIDOS))}); recebido {a.host!r}",
              file=sys.stderr)
        return 2
    else:
        escuta = endereco = a.host
    token = os.environ.get("LEXIS_TOKEN") or gerar_token()
    config = ConfigServidor(
        token=token, raiz_amostras=a.entrada, golden_csv=a.golden, dir_replay=a.replay,
        dir_execucoes=a.execucoes, dir_front=a.front, cfg=config_do_ambiente(),
        db_url=os.environ.get("LEXIS_DB_URL") or None,
        dominios_email=dominios_do_ambiente(os.environ.get("LEXIS_DOMINIOS_EMAIL", "")),
    )
    app = criar_app(config)
    # o token vai no fragmento (#): o navegador nunca o envia ao servidor nem o registra em logs
    print(f"\nLexis web em  http://{endereco}:{a.porta}/#token={token}\n(o token muda a cada subida; Ctrl+C encerra)\n",
          flush=True)
    uvicorn.run(app, host=escuta, port=a.porta, log_level="warning", access_log=False)
    return 0


def _contratos(_: argparse.Namespace) -> int:
    from lexis.h_interfaces.contracts import exportar

    for destino in exportar():
        print(f"contrato gravado em {destino}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lexis", description="Extração auditável de avisos de eventos corporativos")
    sub = p.add_subparsers(dest="cmd", required=True)

    def comuns(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--entrada", type=Path, default=PADRAO_ENTRADA)
        sp.add_argument("--golden", type=Path, default=PADRAO_GOLDEN)
        sp.add_argument("--replay", type=Path, default=PADRAO_REPLAY, help="pasta das gravações de extração")

    r = sub.add_parser("run", help="processa o lote")
    comuns(r)
    r.add_argument("--saida", type=Path, default=PADRAO_SAIDA)
    r.add_argument("--modo", choices=["replay", "auto", "live"], default="replay",
                   help="replay: só gravações | auto: gravação, senão API | live: sempre API (exige ANTHROPIC_API_KEY)")
    r.add_argument("--forcar", action="store_true", help="ignora resultados já gerados (idempotência)")
    r.add_argument("--sem-ocr", action="store_true")
    r.set_defaults(func=_run)

    v = sub.add_parser("avaliar", help="avaliação por mutação: injeta defeitos e mede se deixam de ser aprovados")
    comuns(v)
    v.add_argument("--saida", type=Path, default=PADRAO_SAIDA)
    v.set_defaults(func=_avaliar)

    au = sub.add_parser("auditar", help="verifica se a trilha, os registros e as decisões de uma execução são os gravados")
    au.add_argument("pasta", type=Path,
                    help="pasta da execução (f_data/b_output/report_yymmdd_hhmm; na tela, .../<execução>/saida)")
    au.set_defaults(func=_auditar)

    s = sub.add_parser("serve", help="sobe a interface web local (API + front), somente em loopback")
    comuns(s)
    s.add_argument("--host", default="127.0.0.1", help="somente loopback")
    s.add_argument("--porta", type=int, default=8000)
    s.add_argument("--container", action="store_true",
                   help="dentro de um container: escuta na interface do container (ver docker-compose.yml)")
    s.add_argument("--execucoes", type=Path, default=PADRAO_EXECUCOES, help="pasta onde as execuções da tela ficam")
    s.add_argument("--front", type=Path, default=PADRAO_FRONT, help="pasta do front compilado (npm run build)")
    s.set_defaults(func=_serve)

    db = sub.add_parser("db", help="banco SQL (LEXIS_DB_URL): projeção consultável das execuções")
    dbs = db.add_subparsers(dest="acao", required=True)
    di = dbs.add_parser("importar", help="projeta (ou reprojeta) pastas de execução no banco; idempotente")
    di.add_argument("pastas", type=Path, nargs="+")
    di.set_defaults(func=_db_importar)

    ad = sub.add_parser("auditoria", help="auditoria amostral dos APROVADO_AUTO (mede o falso aprovado automático)")
    ads = ad.add_subparsers(dest="acao", required=True)
    so = ads.add_parser("sortear", help="sorteia, por estrato (tipo × fonte), os aprovados a conferir às cegas")
    so.add_argument("--taxa", type=float, default=0.05)
    so.add_argument("--semente", help="reproduz o sorteio (padrão: aleatória, impressa)")
    ads.add_parser("pendentes", help="lista o que falta auditar, pelo prazo de pagamento")
    rg = ads.add_parser("registrar", help="registra o veredito de uma auditoria (não se reescreve)")
    rg.add_argument("id", type=int)
    rg.add_argument("--veredito", choices=["CORRETO", "ERRADO"], required=True)
    rg.add_argument("--auditor", required=True)
    rg.add_argument("--campo", help="campo errado (obrigatório com ERRADO)")
    rg.add_argument("--valor", help="valor correto (obrigatório com ERRADO)")
    rg.add_argument("--observacao")
    ads.add_parser("metricas", help="abstenção e falso aprovado automático estimado, com intervalo de 95%%")
    ad.set_defaults(func=_auditoria)

    us = sub.add_parser("usuario", help="usuários do console (exige banco)")
    uss = us.add_subparsers(dest="acao", required=True)
    uc = uss.add_parser("criar", help="cria uma conta (e-mail + --nome, o apelido); a senha é pedida sem eco (ou LEXIS_SENHA_NOVA)")
    uc.add_argument("email")
    uc.add_argument("--nome", required=True)
    uc.set_defaults(func=_usuario)

    k = sub.add_parser("contratos", help="regrava os contratos publicados (JSON Schema da saída e OpenAPI da API)")
    k.set_defaults(func=_contratos)

    args = p.parse_args(argv)
    configurar_log()  # log estruturado do lote em stderr (só ids, hashes e códigos)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
