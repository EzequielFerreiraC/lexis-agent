"""Contratos publicados: o JSON Schema do registro de saída e o OpenAPI da API local (e_docs/e_contracts) e o DDL do
banco para MySQL (a_src/c_database).

`lexis contratos` regrava os dois depois de uma mudança de propósito (no schema, suba SCHEMA_VERSION; na API, rode
`npm run gen:api` em a_src/a_frontend). Os testes de contrato falham se o arquivo publicado divergir do código.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from lexis.a_domain.models import RegistroSaida

RAIZ = Path(__file__).resolve().parents[4]
DESTINO_SCHEMA = RAIZ / "e_docs" / "e_contracts" / "output_record.schema.json"
DESTINO_OPENAPI = RAIZ / "e_docs" / "e_contracts" / "api.openapi.json"
DESTINO_DDL = RAIZ / "a_src" / "c_database" / "schema_mysql.sql"
CONSULTAS = RAIZ / "a_src" / "c_database" / "consultas.sql"


def _json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def schema_atual() -> str:
    return _json(RegistroSaida.model_json_schema())


def openapi_atual() -> str:
    from lexis.h_interfaces.api.app import criar_app
    from lexis.h_interfaces.api.config import ConfigServidor
    from lexis.h_interfaces.api.security import gerar_token
    from lexis.h_interfaces.api.service import ServicoExecucoes

    with tempfile.TemporaryDirectory() as tmp:  # o serviço cria a pasta de execuções: nada vai para f_data
        config = ConfigServidor(token=gerar_token(), dir_execucoes=Path(tmp),
                                golden_csv=RAIZ / "f_data" / "c_golden_records" / "golden_records.csv")
        servico = ServicoExecucoes(config)
        try:
            return _json(criar_app(config, servico=servico).openapi())
        finally:
            servico.encerrar()


def ddl_mysql() -> str:
    """DDL do esquema da projeção no dialeto do MySQL (o mesmo metadata cria as tabelas em qualquer banco)."""
    from sqlalchemy.dialects import mysql
    from sqlalchemy.schema import CreateIndex, CreateTable

    from lexis.g_adapters.sql_schema import metadata

    dialeto = mysql.dialect()
    partes = ["-- Gerado por `lexis contratos` a partir de lexis/g_adapters/sql_schema.py. Não edite à mão.",
              "-- utf8mb4: o texto dos avisos tem acentos; InnoDB: chaves estrangeiras e transações.", ""]
    for tabela in metadata.sorted_tables:
        ddl = str(CreateTable(tabela).compile(dialect=dialeto)).strip()
        partes.append(f"{ddl} ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;")
        partes += [f"{str(CreateIndex(i).compile(dialect=dialeto)).strip()};" for i in sorted(tabela.indexes, key=str)]
        partes.append("")
    return "\n".join(partes)


def consultas() -> dict[str, str]:
    """Os blocos `-- name:` de a_src/c_database/consultas.sql."""
    blocos: dict[str, str] = {}
    nome: str | None = None
    for linha in CONSULTAS.read_text(encoding="utf-8").splitlines():
        if linha.startswith("-- name:"):
            nome = linha.split(":", 1)[1].strip()
            blocos[nome] = ""
        elif nome and not linha.startswith("--"):
            blocos[nome] += linha + "\n"
    return {k: v.strip().rstrip(";") for k, v in blocos.items()}


def exportar() -> list[Path]:
    gravados = []
    for destino, conteudo in ((DESTINO_SCHEMA, schema_atual()), (DESTINO_OPENAPI, openapi_atual()),
                              (DESTINO_DDL, ddl_mysql())):
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(conteudo, encoding="utf-8")
        gravados.append(destino)
    return gravados
