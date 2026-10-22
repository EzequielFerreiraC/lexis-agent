"""Serviço de execuções: o que a CLI faz (`run`, `avaliar`), exposto como jobs em segundo plano.

Cada execução tem a própria pasta (`<dir_execucoes>/<id>/`): `entrada/` (cópias dos PDFs), `saida/` (JSONs, relatórios,
auditoria) e `gravacoes/` (respostas do modelo desta execução). As gravações versionadas em `c_replay/` servem só de
cache de LEITURA: a interface nunca as sobrescreve.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING

import pdfplumber

import lexis
from lexis.a_domain.models import Decisao, RegistroSaida
from lexis.a_domain.specs import SPECS
from lexis.b_ingestion.pdf import MAX_BYTES, MAX_PAGINAS, ingerir_bytes, renderizar_pagina_png, sha256_bytes
from lexis.c_extraction.config import Config
from lexis.c_extraction.costs import preco_do_modelo
from lexis.c_extraction.prompts import sha_prompt
from lexis.d_validation.reference_base import Golden
from lexis.e_decision.confidence import ORDEM_NIVEL
from lexis.f_application.batch import Resultado, chave_registro, processar_lote, serializar_registro
from lexis.f_application.pipeline import Contexto
from lexis.f_application.report import extracoes_simuladas, publicar_relatorios
from lexis.g_adapters import tesseract_ocr
from lexis.g_adapters.anthropic_api import ExtratorAnthropic, chamador_anthropic
from lexis.g_adapters.local_execution import carregar_golden
from lexis.g_adapters.local_storage import ArmazenamentoEmCamadas, ArmazenamentoLocal
from lexis.g_adapters.local_trail import TrilhaArquivo
from lexis.g_adapters.report_folder import PADRAO_PASTA_RELATORIO, nova_pasta_relatorio
from lexis.h_interfaces.api.config import ConfigServidor

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from lexis.g_adapters.sql_users import Usuario
from lexis.h_interfaces.api.models import (
    Amostra,
    ArquivoEnviado,
    CadastroNovo,
    ChaveInfo,
    ChaveNova,
    Configuracao,
    DocumentoResumo,
    ExecucaoItem,
    ExecucaoNova,
    ExecucaoResumo,
    Limites,
    LoginNovo,
    Modo,
    ModoInfo,
    PaginaExecucoes,
    PaginaMeta,
    RevisaoHumana,
    RevisaoNova,
    Saude,
    SessaoInfo,
    UploadResposta,
    UsuarioInfo,
)

ID_RE = re.compile(rf"^(?:[0-9a-f]{{12}}|{PADRAO_PASTA_RELATORIO})$")  # upload/avaliação: uuid; execução: report_yymmdd_hhmm
PROVEDOR = "Anthropic"  # o extrator e o function calling usam o formato dela; outro provedor = novo adaptador
CHAVE_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,400}")
RELATORIOS_PUBLICOS = ("relatorio_excecoes.md", "relatorio_excecoes.json", "resumo_execucao.json", "auditoria.jsonl")
DPI_IMAGEM = 144
MIN_JUSTIFICATIVA = 10
# Bloqueio por força bruta: MAX_FALHAS_LOGIN erros do mesmo login em JANELA_FALHAS_S segundos bloqueiam o login
MAX_FALHAS_LOGIN = 5
JANELA_FALHAS_S = 15 * 60


class ErroDeUso(Exception):
    """Erro causado pelo pedido do cliente (vira 4xx)."""

    def __init__(self, status: int, detalhe: str) -> None:
        super().__init__(detalhe)
        self.status = status
        self.detalhe = detalhe


def agora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def nome_seguro(nome: str, existentes: set[str] | None = None) -> str:
    """Nome de arquivo apenas com caracteres inofensivos, sempre `.pdf`, sem diretório e único no conjunto."""
    base = PureWindowsPath(PurePosixPath(nome).name).name  # tira diretórios de qualquer sistema
    base = re.sub(r"[^\w.\- ()]", "_", base, flags=re.UNICODE).strip(" .")
    base = re.sub(r"\.pdf$", "", base, flags=re.IGNORECASE)[:96] or "documento"
    candidato = f"{base}.pdf"
    usados = existentes or set()
    n = 2
    while candidato in usados:
        candidato = f"{base}_{n}.pdf"
        n += 1
    return candidato


def _id_valido(valor: str) -> str:
    if not ID_RE.fullmatch(valor):
        raise ErroDeUso(404, "não encontrado")
    return valor


@lru_cache(maxsize=64)
def _png(caminho: str, numero: int) -> bytes:
    doc = ingerir_bytes(Path(caminho).name, Path(caminho).read_bytes())
    return renderizar_pagina_png(doc, numero, DPI_IMAGEM)


def _resumir(nome: str, reg: RegistroSaida, disposicao: str) -> DocumentoResumo:
    niveis = [c.confianca.nivel for c in reg.campos.values() if c.estado.value == "EXTRAIDO"]
    minimo = min(niveis, key=lambda n: ORDEM_NIVEL[n]).value if niveis else None
    custo = reg.auditoria.get("custo_estimado_usd")
    tempo = reg.auditoria.get("tempo_total_ms")
    return DocumentoResumo(
        arquivo=nome, disposicao=disposicao, estado=reg.decisao.estado.value,
        tipo=reg.evento.get("tipo"), fonte=reg.documento.get("fonte"), golden=reg.validacao_golden.status,
        confianca_minima=minimo, motivos=[m.codigo for m in reg.decisao.motivos],
        tokens=int(reg.auditoria.get("tokens_entrada") or 0) + int(reg.auditoria.get("tokens_saida") or 0),
        custo_estimado_usd=float(custo) if custo is not None else None,
        tempo_ms=int(tempo) if tempo is not None else None,
    )


def _contagem(docs: list[DocumentoResumo]) -> dict[str, int]:
    return {d.value: sum(x.estado == d.value for x in docs) for d in Decisao}


class ServicoExecucoes:
    def __init__(self, config: ConfigServidor, golden: Golden | None = None) -> None:
        self.config = config
        self.golden = golden or carregar_golden(config.golden_csv)
        self._lock = threading.RLock()
        # projeções da mesma execução (fim do lote em segundo plano e revisão na requisição) não podem correr juntas:
        # as duas inserem as mesmas linhas e uma perderia para a outra (IntegrityError), deixando a revisão fora do banco
        self._lock_projecao = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lexis-job")  # um job por vez
        self._execucoes: dict[str, ExecucaoResumo] = {}
        # Chave digitada no console: só em memória, vale até o servidor reiniciar e nunca vai para disco. Sem ela, vale a
        # do ambiente (ANTHROPIC_API_KEY). O modelo vem só do ambiente (LEXIS_MODEL).
        self._chave_da_tela: str | None = None
        self._falhas_login: dict[str, list[float]] = {}
        self._engine: Engine | None = None
        if config.db_url:
            from lexis.g_adapters.sql_store import conectar

            self._engine = conectar(config.db_url)
        config.dir_execucoes.mkdir(parents=True, exist_ok=True)
        self._carregar_do_disco()

    # ------------------------------------------------------------------ banco: login e projeção
    @property
    def login_exigido(self) -> bool:
        return self._engine is not None

    def usuario_da_sessao(self, token: str | None) -> Usuario | None:
        if self._engine is None:
            return None
        from lexis.g_adapters.sql_users import usuario_da_sessao

        return usuario_da_sessao(self._engine, token)

    def sessao(self, token: str | None) -> SessaoInfo:
        u = self.usuario_da_sessao(token)
        return SessaoInfo(login_exigido=self.login_exigido,
                          usuario=UsuarioInfo(login=u.login, nome=u.nome) if u else None,
                          dominios_email=list(self.config.dominios_email))

    def entrar(self, req: LoginNovo) -> tuple[SessaoInfo, str]:
        """Confere login e senha e abre uma sessão. A resposta de erro é a mesma para login inexistente e senha
        errada; o mesmo login fica bloqueado depois de MAX_FALHAS_LOGIN erros na janela."""
        if self._engine is None:
            raise ErroDeUso(404, "login desativado: o servidor está sem banco de dados")
        from lexis.g_adapters.sql_users import MAX_SENHA, abrir_sessao, autenticar

        login = req.login.strip().lower()
        instante = time.monotonic()
        with self._lock:
            recentes = [t for t in self._falhas_login.get(login, []) if instante - t < JANELA_FALHAS_S]
            self._falhas_login[login] = recentes
            if len(recentes) >= MAX_FALHAS_LOGIN:
                raise ErroDeUso(429, "muitas tentativas: aguarde alguns minutos e tente de novo")
        senha = req.senha.get_secret_value()
        u = autenticar(self._engine, login, senha) if len(senha) <= MAX_SENHA else None  # sem scrypt de texto enorme
        if u is None:
            with self._lock:
                self._falhas_login.setdefault(login, []).append(instante)
            raise ErroDeUso(401, "e-mail ou senha inválidos")
        with self._lock:
            self._falhas_login.pop(login, None)
        token = abrir_sessao(self._engine, u)
        return self._sessao_de(u), token

    def _sessao_de(self, u: Usuario) -> SessaoInfo:
        return SessaoInfo(login_exigido=True, usuario=UsuarioInfo(login=u.login, nome=u.nome),
                          dominios_email=list(self.config.dominios_email))

    def cadastrar(self, req: CadastroNovo) -> tuple[SessaoInfo, str]:
        """Cria o usuário e já abre a sessão dele."""
        if self._engine is None:
            raise ErroDeUso(404, "cadastro desativado: o servidor está sem banco de dados")
        from lexis.g_adapters.sql_users import LoginEmUso, abrir_sessao, criar_usuario, dominio, normalizar_email

        aceitos = self.config.dominios_email
        if aceitos and dominio(normalizar_email(req.login)) not in aceitos:
            raise ErroDeUso(400, "use um e-mail " + " ou ".join(f"@{d}" for d in aceitos))
        try:
            u = criar_usuario(self._engine, req.login, req.nome, req.senha.get_secret_value())
        except LoginEmUso as e:
            raise ErroDeUso(409, str(e)) from e
        except ValueError as e:
            raise ErroDeUso(400, str(e)) from e
        return self._sessao_de(u), abrir_sessao(self._engine, u)

    def sair(self, token: str | None) -> None:
        if self._engine is not None:
            from lexis.g_adapters.sql_users import encerrar_sessao

            encerrar_sessao(self._engine, token)

    def _projetar(self, run_id: str) -> None:
        """Atualiza a projeção no banco. Os arquivos são o registro oficial: falha aqui não desfaz a execução nem a
        revisão (já gravadas e seladas); `lexis db importar` reprojeta depois."""
        if self._engine is None:
            return
        from lexis.g_adapters.sql_store import ler_revisoes, projetar_execucao

        saida = ArmazenamentoLocal(self.config.dir_execucoes / run_id / "saida")
        try:
            with self._lock_projecao:  # lê revisoes.jsonl já dentro da trava: a última projeção vê todas as revisões
                projetar_execucao(self._engine, run_id, saida, ler_revisoes(saida.ler("revisoes.jsonl")))
        except Exception as e:  # noqa: BLE001 - sem a mensagem (pode trazer dado do documento ou a URL do banco)
            print(f"aviso: projeção no banco falhou para {run_id} ({type(e).__name__}); rode `lexis db importar`",
                  file=sys.stderr)

    # ------------------------------------------------------------------ modelo (do ambiente) e chave
    def _cfg_efetivo(self) -> Config:
        """A configuração do ambiente, com a chave digitada no console por cima."""
        with self._lock:
            chave = self._chave_da_tela
        return replace(self.config.cfg, api_key=chave) if chave else self.config.cfg

    def configuracao(self) -> Configuracao:
        cfg = self._cfg_efetivo()
        with self._lock:
            da_tela = self._chave_da_tela is not None
        chave = cfg.api_key
        entrada, saida = preco_do_modelo(cfg.modelo, cfg.preco_override) or (None, None)  # sem preço, nunca inventado
        return Configuracao(
            provedor=PROVEDOR, modelo=cfg.modelo, preco_entrada_usd_mtok=entrada, preco_saida_usd_mtok=saida,
            chave=ChaveInfo(configurada=bool(chave), origem=("tela" if da_tela else "ambiente") if chave else None,
                            final=chave[-4:] if chave else None),
        )

    def definir_chave(self, req: ChaveNova) -> Configuracao:
        chave = req.chave.get_secret_value().strip()
        if not CHAVE_RE.fullmatch(chave):  # mensagem fixa: nunca ecoa o que foi digitado
            raise ErroDeUso(400, "a chave não parece uma chave de API da Anthropic (começa com sk-ant-)")
        with self._lock:
            self._chave_da_tela = chave
        return self.configuracao()

    def remover_chave(self) -> Configuracao:
        with self._lock:
            self._chave_da_tela = None  # volta à chave do ambiente, se houver
        return self.configuracao()

    # ------------------------------------------------------------------ catálogo e saúde
    def saude(self) -> Saude:
        cfg = self._cfg_efetivo()
        tem_chave = bool(cfg.api_key)
        modos = [
            ModoInfo(id="replay", disponivel=True,
                     descricao="Usa só as gravações de extração. Sem rede, sem chave e sem custo."),
            ModoInfo(id="auto", disponivel=True,
                     descricao="Usa a gravação se existir; senão chama o modelo e grava (exige chave só quando falta gravação)."),
            ModoInfo(id="live", disponivel=tem_chave,
                     descricao="Sempre chama o modelo (gera custo). Mede o modelo de verdade.",
                     motivo_indisponivel=None if tem_chave else
                     "nenhuma chave de API configurada: informe em Configurações ou defina ANTHROPIC_API_KEY"),
        ]
        return Saude(
            versao_pipeline=lexis.__version__,
            versoes={"regras": f"{SPECS.versao}+{SPECS.sha[:12]}", "prompt_sha": sha_prompt(),
                     "golden_sha": self.golden.sha[:12]},
            modelo=cfg.modelo, modos=modos, ocr_disponivel=tesseract_ocr.disponivel(), orcamento_tokens=cfg.orcamento_tokens,
            gravacoes_simuladas=self._gravacoes_simuladas(),
            limites=Limites(max_bytes_por_arquivo=MAX_BYTES, max_arquivos=self.config.max_arquivos),
        )

    def _gravacoes_simuladas(self) -> bool:
        pasta = self.config.dir_replay
        if not pasta.is_dir():
            return False
        for arq in sorted(pasta.glob("*/*.json"))[:30]:
            try:
                if '"SIMULADA_MANUALMENTE"' in arq.read_text(encoding="utf-8"):
                    return True
            except OSError:
                continue
        return False

    # ------------------------------------------------------------------ amostras e uploads
    def listar_amostras(self) -> list[Amostra]:
        raiz = self.config.raiz_amostras
        if not raiz.is_dir():
            return []
        saida = []
        for p in sorted(raiz.glob("*.pdf")):
            if p.is_file():
                dados = p.read_bytes()
                saida.append(Amostra(nome=p.name, tamanho=len(dados), sha256=sha256_bytes(dados)))
        return saida

    def criar_upload(self, arquivos: list[tuple[str, bytes]]) -> UploadResposta:
        if not arquivos or len(arquivos) > self.config.max_arquivos:
            raise ErroDeUso(413 if arquivos else 400, f"envie de 1 a {self.config.max_arquivos} PDFs")
        upload_id = uuid.uuid4().hex[:12]
        pasta = self.config.dir_execucoes / "_uploads" / upload_id
        pasta.mkdir(parents=True, exist_ok=True)
        usados: set[str] = set()
        itens: list[ArquivoEnviado] = []
        for nome, dados in arquivos:
            if len(dados) > MAX_BYTES:
                raise ErroDeUso(413, "arquivo acima do limite de tamanho")
            if not dados.startswith(b"%PDF-"):
                raise ErroDeUso(415, "o arquivo enviado não é um PDF")
            seguro = nome_seguro(nome, usados)
            usados.add(seguro)
            (pasta / seguro).write_bytes(dados)
            itens.append(ArquivoEnviado(nome=seguro, tamanho=len(dados), sha256=sha256_bytes(dados)))
        return UploadResposta(id=upload_id, arquivos=itens)

    # ------------------------------------------------------------------ execuções
    def iniciar_execucao(self, req: ExecucaoNova) -> ExecucaoResumo:
        saude = self.saude()
        info = next(m for m in saude.modos if m.id == req.modo)
        if not info.disponivel:
            raise ErroDeUso(400, info.motivo_indisponivel or "modo indisponível")
        if req.modo == "live" and not req.confirmar_live:
            raise ErroDeUso(400, "o modo live gera custo: confirme explicitamente")
        origem_dir, nomes = self._resolver_origem(req)
        pasta = nova_pasta_relatorio(self.config.dir_execucoes)
        run_id = pasta.name
        (pasta / "entrada").mkdir()
        for nome in nomes:
            shutil.copyfile(origem_dir / nome, pasta / "entrada" / nome)
        resumo = ExecucaoResumo(
            id=run_id, criada_em=agora(), estado="NA_FILA", modo=req.modo, origem=req.origem, total=len(nomes),
            concluidos=0, contagem={d.value: 0 for d in Decisao}, sem_ocr=req.sem_ocr,
        )
        with self._lock:
            self._execucoes[run_id] = resumo
            self._salvar(resumo)
        self._pool.submit(self._rodar_execucao, run_id)
        return resumo.model_copy(deep=True)

    def _resolver_origem(self, req: ExecucaoNova) -> tuple[Path, list[str]]:
        if req.origem == "amostras":
            disponiveis = {a.nome for a in self.listar_amostras()}
            base, pedidos = self.config.raiz_amostras, req.arquivos
        else:
            if not req.upload_id:
                raise ErroDeUso(400, "informe o upload_id")
            base = self.config.dir_execucoes / "_uploads" / _id_valido(req.upload_id)
            if not base.is_dir():
                raise ErroDeUso(404, "upload não encontrado")
            disponiveis = {p.name for p in base.glob("*.pdf")}
            pedidos = req.arquivos
        escolhidos = sorted(disponiveis) if pedidos is None else pedidos
        if not escolhidos:
            raise ErroDeUso(400, "nenhum documento para processar")
        desconhecidos = [n for n in escolhidos if n not in disponiveis]  # só nomes que o servidor listou
        if desconhecidos or len(escolhidos) > self.config.max_arquivos:
            raise ErroDeUso(400, "documento desconhecido ou excesso de documentos")
        return base, list(dict.fromkeys(escolhidos))

    def _contexto(self, pasta: Path, modo: str, usar_ocr: bool) -> Contexto:
        gravacoes = ArmazenamentoEmCamadas(
            ArmazenamentoLocal(pasta / "gravacoes"), ArmazenamentoLocal(self.config.dir_replay))
        cfg = self._cfg_efetivo()
        return Contexto(golden=self.golden, modo=modo, cfg=cfg, gravacoes=gravacoes, usar_ocr=usar_ocr,
                        cliente_factory=lambda: ExtratorAnthropic(cfg), chamador_factory=chamador_anthropic,
                        leitor_ocr=tesseract_ocr.ler)

    def _rodar_execucao(self, run_id: str) -> None:
        pasta = self.config.dir_execucoes / run_id
        with self._lock:
            resumo = self._execucoes[run_id]
            resumo.estado = "EM_ANDAMENTO"
            self._salvar(resumo)
        saida = ArmazenamentoLocal(pasta / "saida")

        def ao_concluir(indice: int, total: int, res: Resultado) -> None:
            nome, reg, disposicao = res
            if disposicao in ("DUPLICADO_NO_LOTE", "NAO_PROCESSADO"):
                saida.gravar(chave_registro(nome), serializar_registro(reg))
            with self._lock:
                r = self._execucoes[run_id]
                r.documentos.append(_resumir(nome, reg, disposicao))
                r.concluidos = indice
                r.contagem = _contagem(r.documentos)
                self._salvar(r)

        try:
            ctx = self._contexto(pasta, resumo.modo, not resumo.sem_ocr)
            resultados, lote_id = processar_lote(
                ArmazenamentoLocal(pasta / "entrada"), saida, TrilhaArquivo(pasta / "saida" / "auditoria.jsonl"), ctx,
                ao_concluir=ao_concluir)
            publicar_relatorios(saida, resultados, lote_id)
            with self._lock:
                r = self._execucoes[run_id]
                r.documentos = [_resumir(n, reg, d) for n, reg, d in resultados]
                r.contagem = _contagem(r.documentos)
                r.extracoes_simuladas = extracoes_simuladas([reg for _, reg, _ in resultados])
                r.versoes = resultados[0][1].versoes if resultados else {}
                r.estado, r.concluida_em = "CONCLUIDA", agora()
                self._salvar(r)
            self._projetar(run_id)
        except Exception as e:  # nunca expõe a mensagem (pode conter trecho de documento)
            with self._lock:
                r = self._execucoes[run_id]
                r.estado, r.concluida_em, r.erro = "FALHOU", agora(), f"falha inesperada ({type(e).__name__})"
                self._salvar(r)

    def listar_execucoes(self, limite: int, deslocamento: int) -> PaginaExecucoes:
        limite = max(1, min(limite, self.config.max_por_pagina))
        deslocamento = max(0, deslocamento)
        with self._lock:
            itens = sorted(self._execucoes.values(), key=lambda r: (r.criada_em, r.id), reverse=True)
            pagina = itens[deslocamento: deslocamento + limite]
            return PaginaExecucoes(
                itens=[ExecucaoItem(**r.model_dump(include=set(ExecucaoItem.model_fields))) for r in pagina],
                total=len(itens), limite=limite, deslocamento=deslocamento,
            )

    def obter_execucao(self, run_id: str) -> ExecucaoResumo:
        with self._lock:
            r = self._execucoes.get(_id_valido(run_id))
            if r is None:
                raise ErroDeUso(404, "execução não encontrada")
            return r.model_copy(deep=True)

    def _nome_da_execucao(self, run_id: str, nome: str) -> str:
        if nome not in {d.arquivo for d in self.obter_execucao(run_id).documentos}:
            raise ErroDeUso(404, "documento não encontrado nesta execução")
        return nome

    def _bruto_do_registro(self, run_id: str, nome: str) -> bytes:
        nome = self._nome_da_execucao(run_id, nome)
        bruto = ArmazenamentoLocal(self.config.dir_execucoes / run_id / "saida").ler(chave_registro(nome))
        if bruto is None:
            raise ErroDeUso(404, "registro não encontrado")
        return bruto

    def obter_registro(self, run_id: str, nome: str) -> RegistroSaida:
        return RegistroSaida.model_validate_json(self._bruto_do_registro(run_id, nome))

    # ------------------------------------------------------------------ revisão humana
    def revisar(self, run_id: str, nome: str, req: RevisaoNova, usuario: Usuario | None = None) -> RevisaoHumana:
        """Grava a decisão do operador sobre um documento em REVISAO_HUMANA.

        O registro do pipeline nunca muda: a decisão humana fica ao lado dele, em `execucao.json` (o que a tela
        mostra), em `saida/revisoes.jsonl` (completa) e em `saida/auditoria.jsonl` (só códigos e hashes; sem nome do
        operador nem justificativa). Uma decisão por documento e por execução: refazer exige nova execução.
        """
        if self.login_exigido and usuario is None:
            raise ErroDeUso(401, "sessão ausente ou expirada")
        # com login, quem revisa é o usuário autenticado (o nome digitado é ignorado); sem login, é declarado
        operador = usuario.nome if usuario else " ".join((req.operador or "").split())
        justificativa = req.justificativa.strip()
        if len(operador) < 2:
            raise ErroDeUso(400, "informe quem está revisando")
        if len(justificativa) < MIN_JUSTIFICATIVA:
            raise ErroDeUso(400, f"justifique a decisão (ao menos {MIN_JUSTIFICATIVA} caracteres)")
        bruto = self._bruto_do_registro(run_id, nome)
        reg = RegistroSaida.model_validate_json(bruto)
        if reg.decisao.estado is not Decisao.REVISAO_HUMANA:
            raise ErroDeUso(400, "só documentos em revisão humana recebem decisão do operador")
        motivos = {m.codigo for m in reg.decisao.motivos}
        reconhecidos = set(req.motivos_reconhecidos)
        if not reconhecidos <= motivos:
            raise ErroDeUso(400, "motivo reconhecido que não pertence a esta decisão")
        if req.decisao == "APROVADO_NA_REVISAO" and reconhecidos != motivos:
            raise ErroDeUso(400, "para aprovar, confira e reconheça todos os motivos da revisão")
        pasta = self.config.dir_execucoes / run_id / "saida"
        with self._lock:
            r = self._execucoes[run_id]
            if r.estado != "CONCLUIDA":
                raise ErroDeUso(409, "a execução ainda não terminou")
            doc = next(d for d in r.documentos if d.arquivo == nome)
            if doc.revisao is not None:
                raise ErroDeUso(409, "este documento já foi revisado nesta execução")
            revisao = RevisaoHumana(
                decisao=req.decisao, operador=operador, usuario=usuario.login if usuario else None,
                justificativa=justificativa,
                motivos_reconhecidos=sorted(reconhecidos), decisao_automatica=reg.decisao.estado.value,
                sha256_registro=sha256_bytes(bruto), revisada_em=agora(),
            )
            linha = {"execucao": run_id, "arquivo": nome, **revisao.model_dump()}
            TrilhaArquivo(pasta / "revisoes.jsonl").registrar(linha)
            doc.revisao = revisao
            self._salvar(r)
            TrilhaArquivo(pasta / "auditoria.jsonl").registrar({
                "ts": revisao.revisada_em, "evento": "revisao_humana", "execucao": run_id, "arquivo": nome,
                "decisao": revisao.decisao, "decisao_automatica": revisao.decisao_automatica,
                "motivos_reconhecidos": revisao.motivos_reconhecidos, "sha256_registro": revisao.sha256_registro,
                "sha256_revisao": sha256_bytes(json.dumps(linha, ensure_ascii=False).encode()),
            })
        self._projetar(run_id)
        return revisao.model_copy(deep=True)

    def _caminho_pdf(self, run_id: str, nome: str) -> Path:
        nome = self._nome_da_execucao(run_id, nome)
        caminho = self.config.dir_execucoes / run_id / "entrada" / nome
        if not caminho.is_file():
            raise ErroDeUso(404, "documento não encontrado")
        return caminho

    def meta_pagina(self, run_id: str, nome: str, numero: int) -> PaginaMeta:
        caminho = self._caminho_pdf(run_id, nome)
        with pdfplumber.open(io.BytesIO(caminho.read_bytes())) as pdf:
            total = len(pdf.pages)
            if not 1 <= numero <= min(total, MAX_PAGINAS):
                raise ErroDeUso(404, "página inexistente")
            pg = pdf.pages[numero - 1]
            return PaginaMeta(numero=numero, total_paginas=total, largura_pt=float(pg.width), altura_pt=float(pg.height))

    def imagem_pagina(self, run_id: str, nome: str, numero: int) -> bytes:
        self.meta_pagina(run_id, nome, numero)  # valida existência e limites
        return _png(str(self._caminho_pdf(run_id, nome)), numero)

    def caminho_relatorio(self, run_id: str, arquivo: str) -> Path:
        if arquivo not in RELATORIOS_PUBLICOS:  # lista fechada: nenhum nome vindo do cliente vira caminho
            raise ErroDeUso(404, "relatório não encontrado")
        self.obter_execucao(run_id)
        caminho = self.config.dir_execucoes / _id_valido(run_id) / "saida" / arquivo
        if not caminho.is_file():
            raise ErroDeUso(404, "relatório ainda não disponível")
        return caminho

    # ------------------------------------------------------------------ persistência
    def _salvar(self, r: ExecucaoResumo) -> None:
        (self.config.dir_execucoes / r.id / "execucao.json").write_text(r.model_dump_json(indent=2), encoding="utf-8")

    def _carregar_do_disco(self) -> None:
        raiz = self.config.dir_execucoes
        for arq in raiz.glob("*/execucao.json"):
            try:
                r = ExecucaoResumo.model_validate_json(arq.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if r.estado in ("NA_FILA", "EM_ANDAMENTO"):  # o servidor caiu no meio: nada é retomado
                r.estado, r.erro = "FALHOU", "interrompida: o servidor foi reiniciado durante a execução"
            self._execucoes[r.id] = r

    def encerrar(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


__all__ = ["ErroDeUso", "Modo", "ServicoExecucoes", "nome_seguro"]
