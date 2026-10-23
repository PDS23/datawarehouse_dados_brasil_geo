"""Grava as descrições de infra/diagrama/descricoes_colunas.yaml como COMMENT ON TABLE/COLUMN no PostgreSQL.

O texto das colunas é a documentação "o que é e de onde vem" que o diagrama do banco mostra no balão e no painel de detalhe.
Gera um arquivo SQL (não conecta ao banco); quem tem permissão de dono aplica:

  dw.ps1 etl infra/scripts/aplicar_descricoes_colunas.py        # escreve infra/diagrama/descricoes_colunas.sql
  infra/scripts/dw.ps1 psql -Arquivo infra/diagrama/descricoes_colunas.sql

Regras: o texto próprio de uma tabela sempre é gravado; o `padrao` (por nome de coluna) só preenche coluna sem comentário e NUNCA
sobrescreve um comentário existente (por isso `--padrao-forcado` existe: regrava os padrões também). Colunas ou tabelas que não existem são puladas.
"""
import argparse
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]
ENTRADA = RAIZ / "infra" / "diagrama" / "descricoes_colunas.yaml"
SAIDA = RAIZ / "infra" / "diagrama" / "descricoes_colunas.sql"


def literal(texto):
    return "'" + texto.replace("'", "''") + "'"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--padrao-forcado", action="store_true", help="regrava também os textos do `padrao` onde já há comentário")
    args = ap.parse_args()
    cfg = yaml.safe_load(ENTRADA.read_text(encoding="utf-8"))
    padrao, tabelas = cfg.get("padrao", {}), cfg["tabelas"]
    linhas = ["-- Gerado por infra/scripts/aplicar_descricoes_colunas.py a partir de descricoes_colunas.yaml. Rodar como postgres. Idempotente.",
              "DO $$", "DECLARE n_col integer := 0; n_tab integer := 0; r record;", "BEGIN"]
    # texto próprio das tabelas
    for tabela, itens in tabelas.items():
        sch, nome = tabela.split(".")
        if "_tabela" in itens:
            linhas.append(f"  IF to_regclass('{tabela}') IS NOT NULL THEN EXECUTE format('COMMENT ON %s %s IS %L', "
                          f"CASE (SELECT relkind FROM pg_class WHERE oid = to_regclass('{tabela}')) WHEN 'v' THEN 'VIEW' ELSE 'TABLE' END, "
                          f"'{tabela}', {literal(itens['_tabela'])}); n_tab := n_tab + 1; END IF;")
        for col, texto in itens.items():
            if col == "_tabela":
                continue
            linhas.append(f"  IF EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass('{tabela}') AND attname = '{col}' AND NOT attisdropped) "
                          f"THEN EXECUTE format('COMMENT ON COLUMN %s.%I IS %L', '{tabela}', '{col}', {literal(texto)}); n_col := n_col + 1; END IF;")
    # padrões por nome de coluna: só onde não há comentário (ou sempre, com --padrao-forcado)
    propria = {t: {c for c in it if c != "_tabela"} for t, it in tabelas.items()}
    linhas.append("  FOR r IN SELECT n.nspname || '.' || c.relname AS tabela, a.attname, a.attrelid, col_description(a.attrelid, a.attnum) AS atual")
    linhas.append("           FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace")
    linhas.append("           WHERE n.nspname IN ('dim','vetorial','tabular','resultados','catalogo') AND c.relkind IN ('r','p','v') AND a.attnum > 0 AND NOT a.attisdropped")
    linhas.append("             AND c.relname !~ '^sidra_valor_t[0-9]+$' LOOP")
    linhas.append("    CONTINUE WHEN " + ("false" if args.padrao_forcado else "r.atual IS NOT NULL") + ";")
    primeiro = True
    for col, texto in padrao.items():
        exclui = [t for t, cs in propria.items() if col in cs]
        cond_ex = (" AND r.tabela NOT IN (" + ", ".join(literal(t) for t in exclui) + ")") if exclui else ""
        linhas.append(f"    IF r.attname = '{col}'{cond_ex} THEN EXECUTE format('COMMENT ON COLUMN %s.%I IS %L', r.tabela, r.attname, {literal(texto)}); n_col := n_col + 1; END IF;")
    linhas.append("  END LOOP;")
    linhas.append("  RAISE NOTICE 'comentarios gravados: % colunas, % tabelas', n_col, n_tab;")
    linhas.append("END $$;")
    SAIDA.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"escrito {SAIDA}")


if __name__ == "__main__":
    main()
