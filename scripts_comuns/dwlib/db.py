"""Conexão com o PostGIS e upsert em lote idempotente."""
import os

import psycopg
from psycopg import sql


def conectar():
    """Conecta como o papel de serviço (no compose: etl, senha vinda de ETL_PASSWORD no .env)."""
    senha = os.environ.get("PGPASSWORD")
    if not senha:
        raise RuntimeError("PGPASSWORD vazio. No compose ele vem de ETL_PASSWORD (infra/.env); "
                           "rode infra/scripts/criar_papel_etl.ps1.")
    return psycopg.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "data_warehouse"),
        user=os.environ.get("PGUSER", "etl"),
        password=senha,
        connect_timeout=15,
        # Falha em 60 s em vez de esperar para sempre por uma trava (ex.: outra carga ou uma
        # simulação com transação aberta segurando a mesma linha).
        options="-c lock_timeout=60000",
    )


def id_fonte(conn, nome):
    """id_fonte de dim.fontes pelo nome exato (falha se não existir: cadastre a fonte antes)."""
    with conn.cursor() as cur:
        cur.execute("SELECT id_fonte FROM dim.fontes WHERE nome = %s", (nome,))
        achou = cur.fetchone()
    if not achou:
        raise LookupError(f"fonte '{nome}' não existe em dim.fontes")
    return achou[0]


def upsert(conn, schema, tabela, colunas, linhas, chave, atualizar, comparar=None):
    """INSERT ... ON CONFLICT DO UPDATE em lote, via COPY para uma tabela temporária.

    - linhas: lista de tuplas na ordem de `colunas`. Repetidas na mesma chave: vale a última.
    - chave: colunas da restrição UNIQUE/PK. atualizar: colunas regravadas no conflito.
    - comparar: colunas que decidem se há mudança (padrão: atualizar menos importado_em); a
      linha só é regravada se algum valor comparado difere, então reexecutar não reescreve nada.
    Retorna (inseridas, atualizadas). Não faz commit: quem chama decide.
    """
    if not linhas:
        return 0, 0
    comparar = comparar or [c for c in atualizar if c != "importado_em"]
    unicas = {}
    for linha in linhas:
        unicas[tuple(linha[colunas.index(c)] for c in chave)] = linha
    linhas = list(unicas.values())

    alvo = sql.Identifier(schema, tabela)
    cols = sql.SQL(", ").join(sql.Identifier(c) for c in colunas)
    tmp = sql.Identifier("_tmp_upsert")
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE TEMP TABLE {tmp} ON COMMIT DROP AS SELECT {cols} FROM {alvo} WITH NO DATA")
                    .format(tmp=tmp, cols=cols, alvo=alvo))
        with cur.copy(sql.SQL("COPY {tmp} ({cols}) FROM STDIN").format(tmp=tmp, cols=cols)) as copia:
            for linha in linhas:
                copia.write_row(linha)
        sets = sql.SQL(", ").join(sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in atualizar)
        antigo = sql.SQL(", ").join(sql.SQL("{t}.{c}").format(t=alvo, c=sql.Identifier(c)) for c in comparar)
        novo = sql.SQL(", ").join(sql.SQL("EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in comparar)
        consulta = sql.SQL(
            "INSERT INTO {alvo} ({cols}) SELECT {cols} FROM {tmp} "
            "ON CONFLICT ({chave}) DO UPDATE SET {sets} WHERE ({antigo}) IS DISTINCT FROM ({novo}) "
            "RETURNING (xmax = 0)"
        ).format(alvo=alvo, cols=cols, tmp=tmp, chave=sql.SQL(", ").join(sql.Identifier(c) for c in chave),
                 sets=sets, antigo=antigo, novo=novo)
        cur.execute(consulta)
        resultado = cur.fetchall()
        cur.execute(sql.SQL("DROP TABLE {tmp}").format(tmp=tmp))
    inseridas = sum(1 for (nova,) in resultado if nova)
    return inseridas, len(resultado) - inseridas
