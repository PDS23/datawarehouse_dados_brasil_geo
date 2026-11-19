"""Gera o SQL das permissões do papel consulta_ia: SELECT coluna a coluna, menos as colunas de dado pessoal.

Lê `colunas_pessoais` de infra/diagrama/descricoes_colunas.yaml e `schemas` de servicos/consulta_ia/config.yaml e escreve
servicos/consulta_ia/sql/permissoes_consulta_ia.sql (não conecta ao banco). Quem é dono das tabelas aplica:

  .\\infra\\scripts\\dw.ps1 etl servicos/consulta_ia/scripts/gerar_permissoes.py
  .\\infra\\scripts\\dw.ps1 psql -Arquivo servicos\\consulta_ia\\sql\\permissoes_consulta_ia.sql

Por que coluna a coluna em TODA tabela (e não só nas que têm dado pessoal): falha fechada. Tabela ou coluna nova que um pipeline criar fica
invisível para a IA até este gerador rodar de novo; o erro possível é a IA não ver um dado, nunca ver um dado pessoal por esquecimento.
O SQL revoga tudo e concede de novo numa transação (sem janela), avisa se uma coluna listada como pessoal não existe (erro de digitação)
e avisa se alguma coluna concedida TEM CARA de dado pessoal (cpf, cnpj, hash, autuado, embargado, empregador) sem estar na lista.
"""
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[3]
DESCRICOES = RAIZ / "infra" / "diagrama" / "descricoes_colunas.yaml"
CONFIG = RAIZ / "servicos" / "consulta_ia" / "config.yaml"
SAIDA = RAIZ / "servicos" / "consulta_ia" / "sql" / "permissoes_consulta_ia.sql"

SUSPEITAS = r"(cpf|cnpj|_hash$|autuado|embargado$|nome_embargado|empregador$|socio)"


def literal(texto):
    return "'" + texto.replace("'", "''") + "'"


def main():
    pessoais = yaml.safe_load(DESCRICOES.read_text(encoding="utf-8")).get("colunas_pessoais") or {}
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    papel, schemas = cfg["papel"], cfg["schemas"]
    lista_schemas = ", ".join(schemas)
    arr_schemas = "ARRAY[" + ", ".join(literal(s) for s in schemas) + "]"

    valores = ",\n    ".join(f"({literal(t)}, {literal(c)})" for t, cols in pessoais.items() for c in cols) or "(NULL, NULL)"
    sql = f"""-- Gerado por servicos/consulta_ia/scripts/gerar_permissoes.py. NÃO editar à mão: edite colunas_pessoais em
-- infra/diagrama/descricoes_colunas.yaml (ou schemas em servicos/consulta_ia/config.yaml) e gere de novo. Rodar como postgres. Idempotente.
BEGIN;

-- Revogar no nível da tabela revoga também os privilégios de coluna (documentação do REVOKE).
REVOKE ALL ON ALL TABLES IN SCHEMA {lista_schemas} FROM {papel};

CREATE TEMP TABLE _pessoais (tabela text, coluna text) ON COMMIT DROP;
INSERT INTO _pessoais VALUES
    {valores};

DO $$
DECLARE r record; n_tab int := 0; n_col int := 0; n_oculta int := 0;
BEGIN
  -- coluna listada que não existe: provável erro de digitação na lista (a coluna real ficaria exposta)
  FOR r IN SELECT p.tabela, p.coluna FROM _pessoais p WHERE p.tabela IS NOT NULL AND NOT EXISTS (
             SELECT 1 FROM pg_attribute a WHERE a.attrelid = to_regclass(p.tabela) AND a.attname = p.coluna AND a.attnum > 0 AND NOT a.attisdropped) LOOP
    RAISE WARNING 'coluna pessoal listada nao existe: %.% (confira a lista)', r.tabela, r.coluna;
  END LOOP;

  FOR r IN
    SELECT c.oid, format('%I.%I', n.nspname, c.relname) AS alvo, n.nspname || '.' || c.relname AS nome,
           array_agg(a.attname ORDER BY a.attnum) FILTER (WHERE p.coluna IS NULL) AS liberadas,
           count(p.coluna) AS ocultas
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
    LEFT JOIN _pessoais p ON p.tabela = n.nspname || '.' || c.relname AND p.coluna = a.attname
    WHERE n.nspname = ANY({arr_schemas}) AND c.relkind IN ('r', 'p', 'v', 'm', 'f') AND NOT c.relispartition
    GROUP BY c.oid, n.nspname, c.relname
  LOOP
    CONTINUE WHEN r.liberadas IS NULL;
    EXECUTE format('GRANT SELECT (%s) ON %s TO {papel}',
                   (SELECT string_agg(quote_ident(x), ', ') FROM unnest(r.liberadas) AS x), r.alvo);
    n_tab := n_tab + 1; n_col := n_col + cardinality(r.liberadas); n_oculta := n_oculta + r.ocultas;
  END LOOP;

  -- rede de segurança: coluna concedida com cara de dado pessoal
  FOR r IN SELECT table_schema || '.' || table_name AS tabela, column_name FROM information_schema.column_privileges
           WHERE grantee = '{papel}' AND privilege_type = 'SELECT' AND column_name ~* {literal(SUSPEITAS)} LOOP
    RAISE WARNING 'coluna com cara de dado pessoal LIBERADA para {papel}: %.% (se for pessoal, acrescente em colunas_pessoais)', r.tabela, r.column_name;
  END LOOP;

  RAISE NOTICE '{papel}: % tabelas/views, % colunas liberadas, % colunas pessoais ocultas', n_tab, n_col, n_oculta;
END $$;

COMMIT;
"""
    SAIDA.write_text(sql, encoding="utf-8")
    print(f"escrito {SAIDA.relative_to(RAIZ)} ({sum(len(v) for v in pessoais.values())} colunas pessoais em {len(pessoais)} tabelas)")


if __name__ == "__main__":
    main()
