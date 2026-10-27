"""Quem foi embargado? Do identificador do termo (visto no mapa do GeoServer) ao titular, nas fontes de embargo (IBAMA, ICMBio, SEMA-MT).

O GeoServer publica os embargos SEM nome nem documento (views em infra/postgres/views_geoserver.sql), só com os identificadores do termo. Este auxiliar fecha o caminho: dado o
número do TAD (IBAMA), do embargo (ICMBio) ou do termo (SEMA-MT), ou o número do auto de infração ou do processo, devolve o NOME, o tipo de documento e o CNPJ do embargado.
Para pessoa física o banco guarda só o hash do CPF (decisão do projeto): o CPF em si não sai daqui, mas dá para confirmar se um CPF/CNPJ conhecido é o titular, com --documento.

Uso (a partir da raiz do repositório; só quem tem acesso ao banco, porque imprime nome de pessoa):
  .\\infra\\scripts\\dw.ps1 etl infra/scripts/consultar_embargo.py 149615
  .\\infra\\scripts\\dw.ps1 etl infra/scripts/consultar_embargo.py "149615|C|342233" --documento 123.456.789-09     # o titular e esta pessoa? (compara hash/CNPJ)
  .\\infra\\scripts\\dw.ps1 etl infra/scripts/consultar_embargo.py 2023/01623 --tudo                                # inclui versões já fechadas e embargos já desembargados

Procura o identificador em: IBAMA (chave_tad, num_tad, num_auto_infracao, num_processo), ICMBio (numero_emb, numero_ai, processo), SEMA-MT (t_embargo, a_infrac, n_processo).
"""
import argparse
import sys

from dwlib import db, documento

FONTES = [
    ("IBAMA", "vetorial.ibama_embargos", ["chave_tad", "num_tad", "num_auto_infracao", "num_processo"],
     "chave_tad AS termo, uf, municipio, dat_embargo::date AS data, nome_embargado AS nome, tipo_doc_embargado AS tipo, cpf_cnpj_embargado AS cnpj, cpf_embargado_hash AS hash, "
     "coalesce(sit_desembargo, '-') AS situacao", "chave_tad"),
    ("ICMBio", "vetorial.icmbio_areas_embargadas", ["numero_emb", "numero_ai", "processo"],
     "numero_emb || ' ' || coalesce(serie, '') AS termo, uf, municipio, data_embargo AS data, autuado AS nome, tipo_doc_autuado AS tipo, cpf_cnpj AS cnpj, cpf_autuado_hash AS hash, "
     "coalesce(julgamento, '-') AS situacao", "numero_emb, serie, uf, municipio, data_embargo, autuado, tipo_doc_autuado, cpf_cnpj, cpf_autuado_hash, julgamento"),
    ("SEMA-MT embargada", "vetorial.sema_mt_areas_embargadas", ["t_embargo", "a_infrac", "n_processo"],
     "t_embargo AS termo, 'MT' AS uf, NULL::text AS municipio, data_lavratura AS data, nome, tipo_doc_embargado AS tipo, cpf_cnpj AS cnpj, cpf_embargado_hash AS hash, "
     "'embargada' AS situacao", "t_embargo, data_lavratura, nome, tipo_doc_embargado, cpf_cnpj, cpf_embargado_hash"),
    ("SEMA-MT DESEMBARGADA", "vetorial.sema_mt_areas_desembargadas", ["t_embargo", "a_infrac", "n_processo"],
     "t_embargo AS termo, 'MT' AS uf, NULL::text AS municipio, data_lavratura AS data, nome, tipo_doc_embargado AS tipo, cpf_cnpj AS cnpj, cpf_embargado_hash AS hash, "
     "'DESEMBARGADA (encerrado)' AS situacao", "t_embargo, data_lavratura, nome, tipo_doc_embargado, cpf_cnpj, cpf_embargado_hash"),
]


def main():
    ap = argparse.ArgumentParser(description="Titular de um embargo (IBAMA, ICMBio, SEMA-MT) a partir do identificador do termo")
    ap.add_argument("identificador", help="numero do TAD / termo / auto de infracao / processo (como aparece na camada do GeoServer)")
    ap.add_argument("--documento", help="CPF ou CNPJ conhecido (ex.: do produtor): diz se e o titular do embargo")
    ap.add_argument("--tudo", action="store_true", help="inclui versoes ja fechadas e, no IBAMA, embargos desembargados")
    args = ap.parse_args()
    ident = args.identificador.strip()
    if len(ident) < 4:
        raise SystemExit("identificador curto demais (minimo 4 caracteres)")
    h_ref = cnpj_ref = None
    if args.documento:
        tipo, digitos, valido = documento.classificar(args.documento)
        if tipo == "CPF":
            chave = documento.chave()
            if chave is None:
                raise SystemExit("sem a chave do HMAC: nao da para comparar CPF")
            h_ref = documento.hash_cpf(digitos, chave)
        elif tipo == "CNPJ":
            cnpj_ref = digitos
        else:
            raise SystemExit("--documento nao reconhecido como CPF nem CNPJ")
    cur = db.conectar().cursor()
    total = 0
    for rotulo, tabela, campos, selecao, agrupa in FONTES:
        onde = " OR ".join(f"{c} = %(i)s" for c in campos)
        vig = "" if args.tudo else " AND vigente_ate IS NULL"
        if rotulo == "IBAMA" and not args.tudo:
            vig += " AND coalesce(sit_desembargo, 'N') <> 'S'"
        cur.execute(f"SELECT DISTINCT {selecao} FROM {tabela} WHERE ({onde}){vig} ORDER BY 1, 4 LIMIT 50", {"i": ident})
        linhas = cur.fetchall()
        if not linhas:
            continue
        print(f"\n{rotulo}: {len(linhas)} registro(s)")
        for termo, uf, mun, data, nome, tipo, cnpj, h, situacao in linhas:
            total += 1
            doc = f"CNPJ {cnpj}" if tipo == "CNPJ" and cnpj else ("CPF (so hash no banco)" if tipo == "CPF" else (f"documento: {cnpj}" if cnpj else "sem documento"))
            titular = ""
            if h_ref or cnpj_ref:
                igual = (h_ref is not None and h == h_ref) or (cnpj_ref is not None and cnpj == cnpj_ref)
                titular = "  <== MESMO TITULAR do documento informado" if igual else "  (titular diferente do documento informado)"
            print(f"  termo {termo} | {uf or '-'} {mun or ''} | {data or 's/ data'} | {situacao} | {nome or 'sem nome'} | {doc}{titular}")
    if not total:
        print("Nenhum embargo com esse identificador (confira o numero; --tudo inclui versoes fechadas e desembargados).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
