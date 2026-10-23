"""Registro de execuções (catalogo.cargas) e do dataset (catalogo.datasets)."""
import json

from psycopg import sql


class Carga:
    """Contexto que registra uma execução de pipeline em catalogo.cargas.

        with Carga(conn, "ibge_pam", dataset="tabular.ibge_pam", parametros={...}) as carga:
            ...
            carga.lidas += n; carga.inseridas += i; carga.atualizadas += a; carga.rejeitadas += r
            carga.avisos.append("texto")

    Na saída grava status 'ok' ou 'falhou' (com a mensagem do erro) e os contadores. O registro de
    início é confirmado (commit) na hora, para constar mesmo se o processo morrer.
    Com simular=True não grava nada.

    Ao terminar com sucesso roda ANALYZE na tabela do dataset (e nas de `carga.analisar`, "schema.tabela"),
    para o planejador já ter estatísticas novas na primeira consulta depois da coleta, sem esperar o autovacuum.
    Precisa do privilégio MAINTAIN do papel etl (infra/postgres/manutencao.sql); se faltar, só avisa.
    """

    def __init__(self, conn, pipeline, dataset=None, parametros=None, simular=False):
        self.conn, self.pipeline, self.dataset = conn, pipeline, dataset
        self.parametros, self.simular = parametros or {}, simular
        self.lidas = self.inseridas = self.atualizadas = self.rejeitadas = 0
        self.avisos = []
        self.analisar = []
        self.id = None

    def __enter__(self):
        if self.simular:
            return self
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO catalogo.cargas (pipeline, dataset, parametros) VALUES (%s, %s, %s) RETURNING id",
                        (self.pipeline, self.dataset, json.dumps(self.parametros, default=str)))
            self.id = cur.fetchone()[0]
        self.conn.commit()
        return self

    def __exit__(self, tipo, erro, _tb):
        if self.simular or self.id is None:
            return False
        self.conn.rollback()  # descarta qualquer transação pendente antes de registrar o fim
        mensagem = " | ".join(self.avisos[:20]) or None
        status = "ok"
        if erro is not None:
            status = "falhou"
            mensagem = f"{tipo.__name__}: {erro}"[:2000]
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE catalogo.cargas SET finalizada_em = now(), status = %s, linhas_lidas = %s, "
                "linhas_inseridas = %s, linhas_atualizadas = %s, linhas_rejeitadas = %s, mensagem = %s WHERE id = %s",
                (status, self.lidas, self.inseridas, self.atualizadas, self.rejeitadas, mensagem, self.id))
        self.conn.commit()
        if erro is None:
            self._analisar()
        return False

    def _analisar(self):
        tabelas = list(dict.fromkeys(([self.dataset] if self.dataset else []) + self.analisar))
        for t in tabelas:
            schema, _, tabela = t.partition(".")
            try:
                with self.conn.cursor() as cur:
                    cur.execute(sql.SQL("ANALYZE {}.{}").format(sql.Identifier(schema), sql.Identifier(tabela)))
                self.conn.commit()
                print(f"ANALYZE {t}", flush=True)
            except Exception as e:  # a coleta ja foi gravada; falha aqui nao a invalida
                self.conn.rollback()
                print(f"AVISO: ANALYZE {t} nao rodou ({str(e).splitlines()[0]})", flush=True)


def registrar_dataset(conn, nome, schema_tabela, id_fonte, ano_referencia=None, licenca=None, observacoes=None, tipo="tabular"):
    """Cria ou atualiza a linha do dataset em catalogo.datasets (chave: schema_tabela). Sem commit.
    tipo: 'tabular' (padrão), 'vetor' ou 'raster' (só vale na criação da linha)."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM catalogo.datasets WHERE schema_tabela = %s", (schema_tabela,))
        achou = cur.fetchone()
        if achou:
            cur.execute("UPDATE catalogo.datasets SET nome = %s, id_fonte = %s, ano_referencia = %s, "
                        "data_importacao = current_date, licenca = coalesce(%s, licenca), "
                        "observacoes = coalesce(%s, observacoes) WHERE id = %s",
                        (nome, id_fonte, ano_referencia, licenca, observacoes, achou[0]))
        else:
            cur.execute("INSERT INTO catalogo.datasets (nome, tipo, id_fonte, schema_tabela, ano_referencia, "
                        "data_importacao, licenca, observacoes) VALUES (%s, %s, %s, %s, %s, current_date, %s, %s)",
                        (nome, tipo, id_fonte, schema_tabela, ano_referencia, licenca, observacoes))
