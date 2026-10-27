"""Consulta por CPF ou CNPJ nas fontes de embargo e na lista suja (IBAMA, ICMBio, SEMA-MT e MTE), sem expor a chave do hash nem gravar o documento.

O banco não guarda CPF de pessoa física, só o HMAC-SHA256 (dwlib/documento.py). Este script calcula o HMAC do CPF informado com a chave do projeto e procura o hash;
para CNPJ procura o número. Não imprime o documento nem a chave, e só lê (SELECT).

Uso (a partir da raiz do repositório; o documento vai por variável de ambiente ou prompt para não ficar no histórico do shell, ou como argumento se você aceitar isso):
  .\\infra\\scripts\\dw.ps1 etl infra/scripts/consultar_documento.py 123.456.789-09
  .\\infra\\scripts\\dw.ps1 etl infra/scripts/consultar_documento.py 12345678000199 --tudo      # inclui embargos já desembargados/cancelados (IBAMA)

Resultado: por fonte, quantos termos/polígonos vigentes e os identificadores (número do embargo, UF, data), nunca o nome nem o documento.
`--tudo` também inclui, no IBAMA, os já desembargados/cancelados e, na SEMA-MT, as áreas desembargadas.
"""
import argparse
import sys

from dwlib import db, documento


def main():
    ap = argparse.ArgumentParser(description="IBAMA, ICMBio, SEMA-MT e MTE por CPF/CNPJ (so leitura)")
    ap.add_argument("documento", help="CPF ou CNPJ, com ou sem pontuacao")
    ap.add_argument("--tudo", action="store_true", help="inclui embargos do IBAMA ja desembargados/cancelados e as areas desembargadas da SEMA-MT")
    args = ap.parse_args()
    tipo, digitos, valido = documento.classificar(args.documento)
    if tipo not in ("CPF", "CNPJ"):
        raise SystemExit("documento nao reconhecido como CPF nem CNPJ")
    aviso = "" if valido else " (ATENCAO: digitos verificadores nao conferem; a busca segue mesmo assim)"
    print(f"Documento reconhecido como {tipo}{aviso}")
    if tipo == "CPF":
        chave = documento.chave()
        if chave is None:
            raise SystemExit("sem a chave do HMAC (DW_CHAVE_HASH_CPF ou ibama/embargos/segredo/chave_hash_cpf.key): nao da para buscar CPF")
        h = documento.hash_cpf(digitos, chave)
        filtro_ibama, filtro_icmbio, filtro_sema, filtro_mte, par = "cpf_embargado_hash = %s", "cpf_autuado_hash = %s", "cpf_embargado_hash = %s", "cpf_empregador_hash = %s", h
    else:
        filtro_ibama, filtro_icmbio, filtro_sema, filtro_mte, par = "cpf_cnpj_embargado = %s", "cpf_cnpj = %s", "cpf_cnpj = %s", "cpf_cnpj = %s", digitos
    conn = db.conectar()
    cur = conn.cursor()
    ativo = "" if args.tudo else " AND coalesce(sit_desembargo, 'N') <> 'S' AND coalesce(sit_cancelado, 'N') <> 'S'"
    cur.execute(f"SELECT chave_tad, uf, dat_embargo::date, sit_desembargo, sit_cancelado FROM vetorial.ibama_embargos WHERE vigente_ate IS NULL AND {filtro_ibama}{ativo} ORDER BY dat_embargo", (par,))
    linhas = cur.fetchall()
    print(f"\nIBAMA: {len(linhas)} termo(s) de embargo vigente(s){'' if args.tudo else ' (exclui desembargados e cancelados)'}")
    for r in linhas[:50]:
        print("  TAD", r[0], "|", r[1], "|", r[2], "| desembargo:", r[3], "| cancelado:", r[4])
    if len(linhas) > 50:
        print(f"  ... e mais {len(linhas) - 50}")
    cur.execute(f"SELECT numero_emb, serie, uf, data_embargo, nome_uc, count(*) FROM vetorial.icmbio_areas_embargadas WHERE vigente_ate IS NULL AND {filtro_icmbio} "
                "GROUP BY 1, 2, 3, 4, 5 ORDER BY data_embargo", (par,))
    linhas = cur.fetchall()
    print(f"\nICMBio: {len(linhas)} embargo(s), {sum(r[5] for r in linhas)} poligono(s) vigente(s)")
    for r in linhas[:50]:
        print("  embargo", r[0], r[1] or "", "|", r[2], "|", r[3], "|", r[4], "|", r[5], "poligono(s)")
    tabelas = [("sema_mt_areas_embargadas", "embargada")] + ([("sema_mt_areas_desembargadas", "DESEMBARGADA (encerrado)")] if args.tudo else [])
    for t, rotulo in tabelas:
        cur.execute(f"SELECT t_embargo, n_processo, data_lavratura, dat_lavrat, count(*) FROM vetorial.{t} WHERE vigente_ate IS NULL AND {filtro_sema} GROUP BY 1, 2, 3, 4 ORDER BY 3", (par,))
        linhas = cur.fetchall()
        print(f"\nSEMA-MT ({rotulo}):{len(linhas)} termo(s), {sum(r[4] for r in linhas)} poligono(s) vigente(s)")
        for r in linhas[:50]:
            print("  termo", r[0], "| processo", r[1], "| lavratura", r[2] or r[3], "|", r[4], "poligono(s)")
    cur.execute(f"SELECT ano_acao_fiscal, uf, inclusao_cadastro, trabalhadores_envolvidos FROM tabular.mte_cadastro_empregadores WHERE vigente_ate IS NULL AND {filtro_mte} ORDER BY 1", (par,))
    linhas = cur.fetchall()
    print(f"\nMTE, Cadastro de Empregadores (lista suja): {'CONSTA' if linhas else 'nao consta'} ({len(linhas)} registro(s) vigente(s))")
    for r in linhas:
        print("  acao fiscal", r[0], "|", r[1], "| incluido em", r[2], "|", r[3], "trabalhador(es)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
