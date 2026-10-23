"""Retencao de versoes fechadas dos espelhos (SICAR, PRODES): apaga, depois de um prazo, o que a fonte retirou e nao voltou.

Config: infra/retencao.yaml (prazos por tabela e resultados dependentes). SEM --apagar a rotina so relata: nada e apagado.
Apagar e DELETE definitivo (o backup e o unico caminho de volta): confira o relatorio antes, e faca backup com etiqueta.

Uso (no conteiner etl, a partir de infra/):
  docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl infra/scripts/limpar_versoes_fechadas.py [opcoes]

  OPCOES: --apagar | --tabelas vetorial.sicar_imoveis | --config outro.yaml | --aceitar-volume (libera apagar mais de max_fracao_apagada)

Ordem segura: para cada tabela, apaga primeiro os resultados dependentes das versoes candidatas e depois as versoes, em lotes
(cada lote e uma transacao). Cada execucao com --apagar vira uma linha em catalogo.cargas.
"""
import argparse
import sys
import time
from pathlib import Path

import yaml
from psycopg import sql

from dwlib import db
from dwlib.catalogo import Carga
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # infra
LOTE = 50000


def log(*a):
    print(*a, flush=True)


def ident(nome):
    return sql.Identifier(*nome.split("."))


def candidatas(cur, T, chave, dias_removidas, dias_substituidas):
    """Preenche _ids com as versoes candidatas; retorna (removidas, substituidas)."""
    cur.execute("CREATE TEMP TABLE _ids (id bigint PRIMARY KEY, motivo text NOT NULL) ON COMMIT DROP")
    cond_chave = sql.SQL(" AND ").join(sql.SQL("t.{c} = m.{c}").format(c=sql.Identifier(c)) for c in chave)
    cols = sql.SQL(", ").join(sql.Identifier(c) for c in chave)
    if dias_removidas is not None:
        cur.execute(sql.SQL("""INSERT INTO _ids
            WITH mortas AS (SELECT {cols} FROM {T} GROUP BY {cols}
                            HAVING bool_and(vigente_ate IS NOT NULL) AND max(vigente_ate) < current_date - %s)
            SELECT t.id, 'removida' FROM {T} t JOIN mortas m ON {cond}""").format(cols=cols, T=ident(T), cond=cond_chave), (dias_removidas,))
    if dias_substituidas is not None:
        cond_v = sql.SQL(" AND ").join(sql.SQL("v.{c} = t.{c}").format(c=sql.Identifier(c)) for c in chave)
        cur.execute(sql.SQL("""INSERT INTO _ids SELECT t.id, 'substituida' FROM {T} t
            WHERE t.vigente_ate IS NOT NULL AND t.vigente_ate < current_date - %s
              AND EXISTS (SELECT 1 FROM {T} v WHERE {cond_v} AND v.vigente_ate IS NULL)
            ON CONFLICT DO NOTHING""").format(T=ident(T), cond_v=cond_v), (dias_substituidas,))
    cur.execute("SELECT count(*) FILTER (WHERE motivo = 'removida'), count(*) FILTER (WHERE motivo = 'substituida') FROM _ids")
    return cur.fetchone()


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="Retencao de versoes fechadas dos espelhos")
    ap.add_argument("--apagar", action="store_true", help="apaga de verdade (padrao: so relata)")
    ap.add_argument("--tabelas", help="schema.tabela separadas por virgula (padrao: todas do retencao.yaml)")
    ap.add_argument("--config", default=str(RAIZ / "retencao.yaml"))
    ap.add_argument("--aceitar-volume", action="store_true")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    escolhidas = set(t.strip() for t in args.tabelas.split(",")) if args.tabelas else None
    tabelas = [t for t in cfg["tabelas"] if not escolhidas or t["tabela"] in escolhidas]
    if escolhidas and len(tabelas) != len(escolhidas):
        raise SystemExit(f"tabelas fora do retencao.yaml: {escolhidas - {t['tabela'] for t in tabelas}}")

    conn = db.conectar()
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = 0")
    t_ini = time.time()
    log(f"== retencao de versoes fechadas ({'APAGANDO' if args.apagar else 'so relatorio, nada e apagado'})")
    with Carga(conn, "limpeza_versoes", dataset=",".join(t["tabela"] for t in tabelas), parametros=vars(args), simular=not args.apagar) as carga:
        for t in tabelas:
            T, chave = t["tabela"], t["chave"]
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass(%s)", (T,))
                if cur.fetchone()[0] is None:
                    log(f"  {T}: tabela nao existe, pulada")
                    continue
                deps = []
                for d in t.get("dependentes", []):
                    cur.execute("SELECT to_regclass(%s)", (d["tabela"],))
                    if cur.fetchone()[0] is None:
                        log(f"  {T}: dependente {d['tabela']} ainda nao existe, ignorado")
                    else:
                        deps.append(d)
                cur.execute(sql.SQL("SELECT count(*), count(*) FILTER (WHERE vigente_ate IS NULL) FROM {T}").format(T=ident(T)))
                total, vigentes = cur.fetchone()
                dias_rem = t.get("dias_removidas", cfg.get("dias_removidas_padrao"))
                dias_sub = t.get("dias_substituidas", cfg.get("dias_substituidas_padrao"))
                n_rem, n_sub = candidatas(cur, T, chave, dias_rem, dias_sub)
                n = n_rem + n_sub
                dep_n = {}
                for d in deps:
                    cur.execute(sql.SQL("SELECT count(*) FROM {D} WHERE {c} IN (SELECT id FROM _ids)").format(D=ident(d["tabela"]), c=sql.Identifier(d["coluna"])))
                    dep_n[d["tabela"]] = cur.fetchone()[0]
                log(f"  {T}: {total:,} versoes ({vigentes:,} vigentes, {total - vigentes:,} fechadas); candidatas a apagar: {n_rem:,} de registros "
                    f"removidos ha mais de {dias_rem} dias, {n_sub:,} substituidas (prazo {dias_sub}); "
                    f"resultados dependentes: {dep_n or 'nenhum'}".replace(",", "."))
                carga.lidas += n
                if not args.apagar or n == 0:
                    conn.rollback()
                    continue
                if n > total * cfg["max_fracao_apagada"] and not args.aceitar_volume:
                    conn.rollback()
                    raise RuntimeError(f"{T}: {n} candidatas = mais de {cfg['max_fracao_apagada']:.0%} da tabela: NAO apagado (confira; --aceitar-volume libera)")
                cur.execute("SELECT id FROM _ids ORDER BY id")
                ids = [r[0] for r in cur.fetchall()]
                conn.commit()                                   # _ids e temporaria (ON COMMIT DROP): guardamos a lista em memoria
            apagadas, apagadas_dep = 0, 0
            for ini in range(0, len(ids), LOTE):
                lote = ids[ini:ini + LOTE]
                with conn.cursor() as cur:
                    for d in deps:                              # dependentes primeiro (a ordem do yaml: o controle por ultimo)
                        cur.execute(sql.SQL("DELETE FROM {D} WHERE {c} = ANY(%s)").format(D=ident(d["tabela"]), c=sql.Identifier(d["coluna"])), (lote,))
                        apagadas_dep += cur.rowcount
                    cur.execute(sql.SQL("DELETE FROM {T} WHERE id = ANY(%s)").format(T=ident(T)), (lote,))
                    apagadas += cur.rowcount
                conn.commit()
            carga.avisos.append(f"{T}: {apagadas} versoes apagadas ({n_rem} de registros removidos, {n_sub} substituidas) e {apagadas_dep} resultados dependentes")
            log(f"  {T}: APAGADAS {apagadas:,} versoes e {apagadas_dep:,} resultados dependentes".replace(",", "."))
        log(f"== fim em {time.time() - t_ini:.0f} s" + ("" if args.apagar else " (relatorio: nada foi apagado; use --apagar)"))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
