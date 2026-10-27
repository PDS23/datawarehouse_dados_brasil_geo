"""Reconciliação de um ESPELHO VERSIONADO (SCD2) a partir de uma tabela temporária de coleta.

Mesma regra do SICAR, do PRODES e do MapBiomas Alerta, para as fontes novas não copiarem a lógica:
  - NOVO       chave que não tem versão vigente entra (vigente_desde = hoje);
  - ALTERADO   algum campo comparado ou a geometria mudou: fecha a versão vigente (vigente_ate = hoje) e insere a nova;
  - AUSENTE    vigente no banco e ausente da coleta: a versão é FECHADA (nada é apagado na coleta);
  - REABERTO   a chave sumiu e voltou IDÊNTICA à última versão fechada: a versão é reaberta (vigente_ate NULL, reaberto_em = hoje);
  - INALTERADO nada é feito.
Trava: se os ausentes passam de `max_queda` dos vigentes, não grava (`aceitar_queda=True` libera).

A tabela de destino T precisa ter: id (identity), as colunas de `campos`, geom (geometry), geom_anomala, geom_origem_texto, id_fonte, importado_em,
vigente_desde, vigente_ate, coletado_em, reaberto_em, e um índice único parcial na chave onde vigente_ate IS NULL.
A tabela temporária `stage` (ON COMMIT DROP, na mesma transação) precisa ter as colunas de `campos` + geom + geom_anomala + geom_origem_texto
e uma única linha por chave. Com `com_geometria=False` (tabela sem geometria) T e `stage` não têm geom, geom_anomala nem geom_origem_texto. Não faz commit nem rollback: quem chama decide (com simular=True nada é escrito, só se conta).
"""
from datetime import date, datetime, timezone


def _juncao(chave, a="c", b="s"):
    return " AND ".join(f"{a}.{k} = {b}.{k}" for k in chave)


def reconciliar(conn, T, chave, comparar, campos, *, fonte, stage="_stage", id_carga=None, max_queda=0.10, aceitar_queda=False,
                simular=False, escopo_sql=None, com_geometria=True, log=print):
    """Reconcilia `stage` com a tabela T. escopo_sql (opcional, com alias `c`) limita quais vigentes podem ser considerados AUSENTES
    (coleta parcial, ex.: uma UF). Retorna um dict com os contadores."""
    cur = conn.cursor()
    hoje, agora = date.today(), datetime.now(timezone.utc)
    esc = f" AND ({escopo_sql})" if escopo_sql else ""
    chaves = ", ".join(chave)
    comp = " OR ".join(f"c.{c} IS DISTINCT FROM s.{c}" for c in comparar)
    geom_dif = ("((c.geom IS NULL) <> (s.geom IS NULL)) OR "
                "(c.geom IS NOT NULL AND s.geom IS NOT NULL AND NOT ST_OrderingEquals(c.geom, s.geom))") if com_geometria else "FALSE"
    idem = " AND ".join(f"NOT (c.{c} IS DISTINCT FROM s.{c})" for c in comparar)
    if com_geometria:
        idem += " AND ((c.geom IS NULL) = (s.geom IS NULL)) AND (c.geom IS NULL OR ST_OrderingEquals(c.geom, s.geom))"

    cur.execute(f"SELECT count(*) FROM {stage}")
    n = cur.fetchone()[0]
    cur.execute(f"CREATE TEMP TABLE _alt ON COMMIT DROP AS SELECT c.id AS id_antigo FROM {stage} s JOIN {T} c ON {_juncao(chave)} AND c.vigente_ate IS NULL "
                f"WHERE {comp} OR {geom_dif}")
    cur.execute(f"CREATE TEMP TABLE _aus ON COMMIT DROP AS SELECT c.id AS id_antigo FROM {T} c WHERE c.vigente_ate IS NULL{esc} "
                f"AND NOT EXISTS (SELECT 1 FROM {stage} s WHERE {_juncao(chave)})")
    cur.execute(f"SELECT count(*) FROM {T} c WHERE c.vigente_ate IS NULL{esc}")
    vigentes_antes = cur.fetchone()[0]
    cur.execute("SELECT (SELECT count(*) FROM _alt), (SELECT count(*) FROM _aus)")
    n_alt, n_aus = cur.fetchone()
    cur.execute(f"SELECT count(*) FROM {stage} s WHERE NOT EXISTS (SELECT 1 FROM {T} c WHERE {_juncao(chave)} AND c.vigente_ate IS NULL)")
    n_novos = cur.fetchone()[0]
    cur.execute(f"""CREATE TEMP TABLE _reab ON COMMIT DROP AS
        WITH ult AS (SELECT DISTINCT ON ({", ".join('c.' + k for k in chave)}) c.* FROM {T} c WHERE c.vigente_ate IS NOT NULL
                     AND EXISTS (SELECT 1 FROM {stage} s WHERE {_juncao(chave)})
                     ORDER BY {", ".join('c.' + k for k in chave)}, c.vigente_ate DESC, c.id DESC)
        SELECT c.id AS id_antigo FROM {stage} s JOIN ult c ON {_juncao(chave)}
        WHERE NOT EXISTS (SELECT 1 FROM {T} v WHERE {_juncao(chave, 'v', 's')} AND v.vigente_ate IS NULL) AND {idem}""")
    cur.execute("SELECT count(*) FROM _reab")
    n_reab = cur.fetchone()[0]
    inalterados = n - n_novos - n_alt
    log(f"  vigentes no banco {vigentes_antes} | NOVOS {n_novos - n_reab} | REABERTOS {n_reab} | ALTERADOS {n_alt} | "
        f"AUSENTES da fonte {n_aus} | inalterados {inalterados}")
    stats = dict(lidos=n, vigentes_antes=vigentes_antes, novos=n_novos - n_reab, reabertos=n_reab, alterados=n_alt, ausentes=n_aus,
                 inalterados=inalterados, inseridos=0)
    if vigentes_antes and n_aus > vigentes_antes * max_queda and not aceitar_queda:
        raise RuntimeError(f"{n_aus} ausentes = mais de {max_queda:.0%} dos {vigentes_antes} vigentes: NAO gravado (confira; --aceitar-queda libera)")
    if simular:
        return stats
    cur.execute(f"UPDATE {T} SET vigente_ate = %s WHERE id IN (SELECT id_antigo FROM _alt UNION SELECT id_antigo FROM _aus)", (hoje,))
    cur.execute(f"UPDATE {T} SET vigente_ate = NULL, reaberto_em = %s WHERE id IN (SELECT id_antigo FROM _reab)", (hoje,))
    cols = ", ".join(campos)
    extra_c, extra_s = (", geom, geom_anomala, geom_origem_texto", ", s.geom, s.geom_anomala, s.geom_origem_texto") if com_geometria else ("", "")
    cur.execute(f"""INSERT INTO {T} ({cols}{extra_c}, id_fonte, importado_em, vigente_desde, coletado_em)
                    SELECT {", ".join('s.' + c for c in campos)}{extra_s}, %s, %s, %s, %s
                    FROM {stage} s WHERE NOT EXISTS (SELECT 1 FROM {T} c WHERE {_juncao(chave)} AND c.vigente_ate IS NULL)""",
                (fonte, hoje, hoje, agora))
    stats["inseridos"] = cur.rowcount
    if stats["inseridos"] != n_novos - n_reab + n_alt:
        raise RuntimeError(f"inseridos {stats['inseridos']} != novos {n_novos - n_reab} + alterados {n_alt}: transacao desfeita")
    return stats
