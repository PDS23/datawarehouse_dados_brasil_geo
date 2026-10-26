"""Termos de embargo do IBAMA (CSV dos dados abertos) -> vetorial.ibama_embargos, como ESPELHO VERSIONADO.

Baixa o CSV inteiro (~210 MB, regerado todo dia pelo IBAMA) e reconcilia com o banco igual ao SICAR, ao PRODES, ao MapBiomas Alerta, à FUNAI e ao
DETER (regras em dwlib/espelho.py): embargo novo entra; alterado fecha a versão antiga e insere a nova; embargo que a fonte deixou de publicar tem
a versão fechada (nada é apagado na coleta); embargo que sumiu e voltou idêntico tem a versão reaberta.

Uso (a partir da raiz do repositório):
  .\\infra\\scripts\\dw.ps1 etl ibama/embargos/scripts/embargos.py [opções]

  OPÇÕES: --simular (reconcilia e relata, nada é gravado) | --guardar-bruto (guarda o CSV em bruto/; por padrão NÃO, porque traz CPF completo)
          --aceitar-queda | --destino SCHEMA.TABELA (padrão: o do config.yaml; a tabela precisa existir: sql/01_tabela.sql)

Particularidades (ver LEIAME_embargos.md):
  - sem identificador único: a chave é chave_tad = NUM_TAD|SER_TAD|SEQ_TAD (única nas 116.944 linhas);
  - dado pessoal: tudo entra como o IBAMA publica, exceto o CPF de pessoa física (11 dígitos), que vira HMAC-SHA256 com chave fora do git;
  - ULTIMA_ATUALIZACAO_RELATORIO muda em todas as linhas todo dia: é guardada, mas não entra na comparação (senão tudo seria "alterado");
  - o cabeçalho do CSV tem de ser exatamente o esperado (51 colunas); se o IBAMA mudar o esquema, nada é gravado;
  - datas de embargo absurdas (ex.: 2925) entram como vêm e ficam marcadas em data_embargo_suspeita.
"""
import argparse
import codecs
import csv
import gzip
import hashlib
import hmac
import os
import re
import secrets
import shutil
import sys
import tempfile
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import yaml

from dwlib import db, espelho, http
from dwlib.catalogo import Carga, registrar_dataset
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # ibama/embargos
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
SRID = CFG["srid_gravado"]
NL = chr(10)

# (coluna no banco, coluna no CSV, tipo SQL, conversor). A ordem é a do CSV.
T_TEXTO, T_BIGINT, T_NUM, T_DUPLA, T_TS = "text", "bigint", "numeric", "double precision", "timestamp"
COLUNAS = [
    ("seq_tad", "SEQ_TAD", T_BIGINT), ("des_status_formulario", "DES_STATUS_FORMULARIO", T_TEXTO), ("des_status_formulario_aie", "DES_STATUS_FORMULARIO_AIE", T_TEXTO),
    ("sit_cancelado", "SIT_CANCELADO", T_TEXTO), ("num_tad", "NUM_TAD", T_TEXTO), ("ser_tad", "SER_TAD", T_TEXTO), ("cod_substituicao", "COD_SUBSTITUICAO", T_TEXTO),
    ("dat_embargo", "DAT_EMBARGO", T_TS), ("dat_impressao", "DAT_IMPRESSAO", T_TS), ("forma_entrega", "FORMA_ENTREGA", T_TEXTO),
    ("num_pessoa_embargo", "NUM_PESSOA_EMBARGO", T_BIGINT), ("nome_embargado", "NOME_EMBARGADO", T_TEXTO), ("cpf_cnpj_embargado", "CPF_CNPJ_EMBARGADO", T_TEXTO),
    ("num_processo", "NUM_PROCESSO", T_TEXTO), ("des_tad", "DES_TAD", T_TEXTO), ("cod_municipio", "COD_MUNICIPIO", T_TEXTO), ("municipio", "MUNICIPIO", T_TEXTO),
    ("uf", "UF", T_TEXTO), ("des_localizacao", "DES_LOCALIZACAO", T_TEXTO), ("num_longitude_tad", "NUM_LONGITUDE_TAD", T_DUPLA),
    ("num_latitude_tad", "NUM_LATITUDE_TAD", T_DUPLA), ("deter_prodes", "DETER_PRODES", T_TEXTO), ("id_poligono", "ID_POLIGONO", T_NUM),
    ("embarga_poligono", "EMBARGA_POLIGONO", T_TEXTO), ("qtd_area_embargada", "QTD_AREA_EMBARGADA", T_NUM), ("nome_imovel", "NOME_IMOVEL", T_TEXTO),
    ("tipo_area", "TIPO_AREA", T_TEXTO), ("geom_wkt", "GEOM_AREA_EMBARGADA", T_TEXTO), ("dat_ult_alter_geom", "DAT_ULT_ALTER_GEOM", T_TS),
    ("unid_apresentacao", "UNID_APRESENTACAO", T_TEXTO), ("unid_controle", "UNID_CONTROLE", T_TEXTO), ("sit_desembargo", "SIT_DESEMBARGO", T_TEXTO),
    ("tipo_desembargo", "TIPO_DESEMBARGO", T_TEXTO), ("dat_desembargo", "DAT_DESEMBARGO", T_TS), ("des_desembargo", "DES_DESEMBARGO", T_TEXTO),
    ("seq_auto_infracao", "SEQ_AUTO_INFRACAO", T_BIGINT), ("num_auto_infracao", "NUM_AUTO_INFRACAO", T_TEXTO), ("seq_notificacao", "SEQ_NOTIFICACAO", T_BIGINT),
    ("seq_acao_fiscalizatoria", "SEQ_ACAO_FISCALIZATORIA", T_BIGINT), ("cd_acao_fiscalizatoria", "CD_ACAO_FISCALIZATORIA", T_TEXTO), ("operacao", "OPERACAO", T_TEXTO),
    ("seq_ordem_fiscalizacao", "SEQ_ORDEM_FISCALIZACAO", T_BIGINT), ("ordem_fiscalizacao", "ORDEM_FISCALIZACAO", T_TEXTO), ("unid_ordenadora", "UNID_ORDENADORA", T_TEXTO),
    ("seq_solicitacao_recurso", "SEQ_SOLICITACAO_RECURSO", T_BIGINT), ("solicitacao_recurso", "SOLICITACAO_RECURSO", T_TEXTO),
    ("operacao_sol_recurso", "OPERACAO_SOL_RECURSO", T_TEXTO), ("dat_ult_alteracao", "DAT_ULT_ALTERACAO", T_TS), ("tipo_alteracao", "TIPO_ALTERACAO", T_TEXTO),
    ("justificativa_alteracao", "JUSTIFICATIVA_ALTERACAO", T_TEXTO), ("ultima_atualizacao_relatorio", "ULTIMA_ATUALIZACAO_RELATORIO", T_TS),
]
CABECALHO = [c[1] for c in COLUNAS]
TIPOS = {c[0]: c[2] for c in COLUNAS}
DERIVADOS = ["chave_tad", "tipo_doc_embargado", "cpf_embargado_hash", "id_estado", "id_municipio", "data_embargo_suspeita"]
# campos gravados na tabela (geom_wkt vira geom; o CPF entra como hash e o cpf_cnpj_embargado só guarda o que não é CPF)
CAMPOS = ["chave_tad"] + [c[0] for c in COLUNAS if c[0] != "geom_wkt"] + ["tipo_doc_embargado", "cpf_embargado_hash", "id_estado", "id_municipio", "data_embargo_suspeita"]
NAO_COMPARAR = {"chave_tad", "ultima_atualizacao_relatorio"}
COMPARAR = [c for c in CAMPOS if c not in NAO_COMPARAR] + ["geom_anomala", "geom_origem_texto"]


def log(*a):
    print(*a, flush=True)


def converter(coluna, v):
    v = v.strip()
    if v == "":
        return None
    tipo = TIPOS[coluna]
    if tipo == T_TS:
        return datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
    if tipo == T_DUPLA:
        return float(v)
    if tipo == T_NUM:
        return Decimal(v.replace(".", "").replace(",", ".") if "," in v else v)
    if tipo == T_BIGINT:
        d = Decimal(v)                                    # ids vêm como 1868621.0000000000
        if d != d.to_integral_value():
            raise ValueError(f"{coluna}: valor nao inteiro ({v})")
        return int(d)
    return v


def chave_hash():
    """Chave do HMAC do CPF: variável DW_CHAVE_HASH_CPF, ou arquivo (criado na primeira carga). Nunca é impressa."""
    env = os.environ.get("DW_CHAVE_HASH_CPF")
    if env:
        return env.encode("utf-8"), False
    arq = RAIZ / CFG["arquivo_chave_hash"]
    if arq.exists():
        return arq.read_text(encoding="utf-8").strip().encode("utf-8"), False
    return None, arq


ANEL = re.compile(r"\(([^()]*)\)")


def aneis_invalidos(wkt):
    """True se algum anel do WKT nao fecha (primeiro ponto != ultimo) ou tem menos de 4 pontos: o PostGIS recusa o WKT inteiro nesses casos."""
    for m in ANEL.finditer(wkt):
        pts = [p.strip() for p in m.group(1).split(",")]
        if len(pts) < 4 or pts[0] != pts[-1]:
            return True
    return False


def baixar(sessao, destino):
    """Baixa o CSV para `destino` (em blocos). Retorna (bytes, last-modified)."""
    r = sessao.get(CFG["url_csv"], stream=True, timeout=(30, 600))
    r.raise_for_status()
    esperado = int(r.headers.get("content-length", 0))
    n = 0
    with open(destino, "wb") as f:
        for bloco in r.iter_content(1 << 20):
            f.write(bloco)
            n += len(bloco)
    if esperado and n != esperado:
        raise RuntimeError(f"download truncado: {n} de {esperado} bytes: NADA gravado")
    if n < CFG["tamanho_minimo_bytes"]:
        raise RuntimeError(f"arquivo com {n} bytes (esperado mais de {CFG['tamanho_minimo_bytes']}): o IBAMA trocou o arquivo? NADA gravado")
    return n, r.headers.get("last-modified")


def linhas_csv(caminho):
    """Linhas do CSV (com o \\n), sem quebrar nos separadores exóticos de str.splitlines: o csv junta as linhas dos campos entre aspas."""
    dec = codecs.getincrementaldecoder("utf-8-sig")(errors="strict")
    resto = ""
    with open(caminho, "rb") as f:
        while True:
            bloco = f.read(1 << 20)
            if not bloco:
                break
            resto += dec.decode(bloco)
            pedacos = resto.split(NL)
            resto = pedacos.pop()
            for p in pedacos:
                yield p + NL
    resto += dec.decode(b"", final=True)
    if resto:
        yield resto


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="Termos de embargo do IBAMA (CSV dos dados abertos) -> espelho versionado de vetorial.ibama_embargos")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--guardar-bruto", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    ap.add_argument("--destino", default=CFG["destino_padrao"], help="schema.tabela (precisa existir)")
    args = ap.parse_args()
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", args.destino):
        raise SystemExit("--destino deve ser schema.tabela em minusculas")
    T = args.destino
    t0 = time.time()
    chave, criar_em = chave_hash()
    hoje = date.today()

    with tempfile.TemporaryDirectory() as tmp:
        csv_local = Path(tmp) / "termo_de_embargo.csv"
        n_bytes, modificado = baixar(http.sessao(), csv_local)
        log(f"== IBAMA embargos: CSV baixado, {n_bytes / 1e6:.0f} MB em {time.time() - t0:.0f} s (last-modified: {modificado})")
        csv.field_size_limit(sys.maxsize)
        rd = csv.reader(linhas_csv(csv_local), delimiter=CFG["delimitador"])
        cab = next(rd)
        if cab != CABECALHO:
            faltam, sobram = [c for c in CABECALHO if c not in cab], [c for c in cab if c not in CABECALHO]
            raise RuntimeError(f"cabecalho do CSV mudou: faltam {faltam}, novas {sobram}: NADA gravado")

        conn = db.conectar()
        if chave is None:                                  # primeira carga: cria a chave, SE o banco ainda nao tem hashes de uma chave anterior
            cur0 = conn.cursor()
            cur0.execute(f"SELECT count(*) FROM {T} WHERE cpf_embargado_hash IS NOT NULL")
            if cur0.fetchone()[0]:
                raise RuntimeError(f"a chave do hash de CPF ({criar_em}) nao existe, mas {T} ja tem hashes: recupere a chave (ou apague os hashes de proposito); "
                                   "criar outra mudaria o hash de todo mundo")
            chave = secrets.token_hex(32).encode("utf-8")
            if not args.simular:
                criar_em.parent.mkdir(parents=True, exist_ok=True)
                criar_em.write_text(chave.decode("utf-8"), encoding="utf-8")
                log(f"  chave do hash de CPF criada em {criar_em.relative_to(RAIZ.parents[1])} (fora do git e do Drive; GUARDE uma copia segura)")
        fonte = db.id_fonte(conn, CFG["fonte"])
        with Carga(conn, "ibama_embargos", dataset=T, parametros=vars(args), simular=args.simular) as carga:
            cur = conn.cursor()
            cur.execute("SET statement_timeout = 0")
            cols_stage = ", ".join(f"{c} {TIPOS[c]}" for c, _, _ in COLUNAS)
            cur.execute(f"CREATE TEMP TABLE _stage (chave_tad text, {cols_stage}, tipo_doc_embargado text, cpf_embargado_hash text, id_estado smallint, "
                        "id_municipio integer, data_embargo_suspeita boolean, geom geometry, geom_anomala boolean DEFAULT false, geom_origem_texto text) ON COMMIT DROP")
            nomes = [c for c, _, _ in COLUNAS]
            lidos = malformadas = cpfs = cnpjs = outros = suspeitas = abertos = 0
            ano_min = CFG["ano_embargo_minimo"]
            with cur.copy(f"COPY _stage (chave_tad, {', '.join(nomes)}, tipo_doc_embargado, cpf_embargado_hash, data_embargo_suspeita, geom_anomala, geom_origem_texto) FROM STDIN") as copia:
                for l in rd:
                    if len(l) != len(CABECALHO):
                        malformadas += 1
                        continue
                    reg = {c: converter(c, v) for (c, _, _), v in zip(COLUNAS, l)}
                    lidos += 1
                    reg["chave_tad"] = f"{l[CABECALHO.index('NUM_TAD')].strip()}|{l[CABECALHO.index('SER_TAD')].strip()}|{l[CABECALHO.index('SEQ_TAD')].strip()}"
                    doc = (reg["cpf_cnpj_embargado"] or "").strip()
                    digitos = re.sub(r"\D", "", doc)
                    tipo_doc = cpf_hash = None
                    if doc:
                        if len(digitos) == 11 and digitos == doc:
                            tipo_doc, cpf_hash, cpfs = "CPF", hmac.new(chave, digitos.encode("ascii"), hashlib.sha256).hexdigest(), cpfs + 1
                            reg["cpf_cnpj_embargado"] = None             # CPF de pessoa fisica NAO e guardado
                        elif len(digitos) == 14 and digitos == doc:
                            tipo_doc, cnpjs = "CNPJ", cnpjs + 1
                        else:
                            tipo_doc, outros = "OUTRO", outros + 1
                    reg["tipo_doc_embargado"], reg["cpf_embargado_hash"] = tipo_doc, cpf_hash
                    d = reg["dat_embargo"]
                    reg["data_embargo_suspeita"] = bool(d and (d.year < ano_min or d.date() > hoje))
                    suspeitas += reg["data_embargo_suspeita"]
                    wkt = reg["geom_wkt"]
                    if wkt and not re.match(r"\s*(MULTI)?POLYGON\s*\(", wkt, re.I):
                        raise RuntimeError(f"{reg['chave_tad']}: geometria que nao e POLYGON/MULTIPOLYGON ({wkt[:40]}): NADA gravado")
                    anomala, origem = False, None
                    if wkt and aneis_invalidos(wkt):             # anel aberto: nao vira geometria; o texto original fica em geom_origem_texto
                        anomala, origem, reg["geom_wkt"] = True, f"SRID={SRID};{wkt}", None
                        abertos += 1
                    copia.write_row([reg["chave_tad"]] + [reg[c] for c in nomes] + [reg["tipo_doc_embargado"], reg["cpf_embargado_hash"], reg["data_embargo_suspeita"],
                                                                                    anomala, origem])
            if lidos < CFG["linhas_minimas"]:
                raise RuntimeError(f"so {lidos} linhas no CSV (esperado mais de {CFG['linhas_minimas']}): NADA gravado")
            if malformadas:
                raise RuntimeError(f"{malformadas} linha(s) com numero de colunas diferente do cabecalho: NADA gravado")
            carga.lidas += lidos
            if abertos:
                carga.avisos.append(f"{abertos} poligono(s) com anel aberto ou curto, gravados com geom NULL e o texto original (geom_anomala)")
            log(f"  {lidos:,} termos lidos | CPF {cpfs:,} (so hash) | CNPJ {cnpjs:,} | outro documento {outros:,} | datas de embargo suspeitas {suspeitas}".replace(",", "."))

            cx = CFG["caixa_brasil"]
            caixa = f"ST_MakeEnvelope({cx['lon_min']}, {cx['lat_min']}, {cx['lon_max']}, {cx['lat_max']}, {SRID})"
            cur.execute(f"UPDATE _stage SET geom = ST_SetSRID(ST_GeomFromText(geom_wkt), {SRID}) WHERE geom_wkt IS NOT NULL")
            cur.execute("SELECT count(*) FILTER (WHERE geom IS NOT NULL), count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)) FROM _stage")
            com_geom, invalidas = cur.fetchone()
            cur.execute(f"UPDATE _stage SET geom_anomala = true, geom_origem_texto = ST_AsEWKT(geom), geom = NULL WHERE geom IS NOT NULL AND NOT (geom @ {caixa})")
            anomalas = cur.rowcount + abertos
            if anomalas - abertos:
                carga.avisos.append(f"{anomalas - abertos} poligono(s) fora do Brasil, gravados com geom NULL e o texto original")
            if invalidas:
                carga.avisos.append(f"{invalidas} poligono(s) invalido(s) pelo PostGIS (gravados como vieram)")
            cur.execute(f"ALTER TABLE _stage ALTER COLUMN geom TYPE geometry(MultiPolygon, {SRID}) USING ST_Multi(geom)")
            cur.execute("UPDATE _stage s SET id_estado = e.id_estado FROM dim.estados e WHERE e.sigla_uf = upper(trim(s.uf))")
            cur.execute("UPDATE _stage s SET id_municipio = m.id_municipio FROM dim.municipios m WHERE trim(s.cod_municipio) ~ '^[0-9]{7}$' "
                        "AND m.id_municipio = trim(s.cod_municipio)::integer")
            cur.execute("UPDATE _stage s SET id_municipio = m.id_municipio FROM dim.municipios m WHERE s.id_municipio IS NULL AND trim(s.cod_municipio) ~ '^[0-9]{6}$' "
                        "AND m.id_municipio / 10 = trim(s.cod_municipio)::integer")
            cur.execute("SELECT count(*) FILTER (WHERE id_estado IS NULL), count(*) FILTER (WHERE id_municipio IS NULL) FROM _stage")
            sem_uf, sem_mun = cur.fetchone()
            log(f"  poligonos {com_geom:,} ({invalidas} invalidos, {abertos} com anel aberto, {anomalas - abertos} fora do Brasil) | sem id_estado {sem_uf} | sem id_municipio {sem_mun}".replace(",", "."))
            cur.execute("DELETE FROM _stage s USING (SELECT ctid AS c, row_number() OVER (PARTITION BY chave_tad ORDER BY ctid) AS rn FROM _stage) r "
                        "WHERE s.ctid = r.c AND r.rn > 1")
            if cur.rowcount:
                carga.avisos.append(f"{cur.rowcount} chave_tad repetida(s) na coleta (vale a primeira)")
            cur.execute("CREATE UNIQUE INDEX ON _stage (chave_tad)")
            cur.execute("ANALYZE _stage")

            stats = espelho.reconciliar(conn, T, ["chave_tad"], COMPARAR, CAMPOS, fonte=fonte, id_carga=carga.id, max_queda=CFG["max_queda"],
                                        aceitar_queda=args.aceitar_queda, simular=args.simular, log=log)
            if args.simular:
                conn.rollback()
                log("SIMULACAO: nada foi gravado.")
                return 0
            cur.execute("INSERT INTO catalogo.coletas (dataset, recorte, fonte, url, metodo, total_anunciado, linhas_lidas, novos, versoes_novas, fechados, "
                        "inalterados, id_carga, observacao, reabertos) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (T, "todos", "IBAMA (dados abertos, CSV)", CFG["url_csv"], "CSV inteiro baixado em uma requisicao", lidos, lidos, stats["novos"],
                         stats["alterados"], stats["ausentes"], stats["inalterados"], carga.id,
                         f"last-modified {modificado}; {suspeitas} datas suspeitas; {anomalas} poligonos fora do Brasil", stats["reabertos"]))
            registrar_dataset(conn, "IBAMA - Termos de embargo", T, fonte, ano_referencia=hoje.year, licenca=CFG["licenca"], tipo="vetor",
                              observacoes="CSV termo_de_embargo.csv dos dados abertos do IBAMA (regerado diariamente). Espelho versionado; o CPF de pessoa fisica so como hash. "
                                          "Ver ibama/embargos/LEIAME_embargos.md.")
            conn.commit()
            carga.inseridas += stats["inseridos"]
            carga.atualizadas += stats["ausentes"]
            if args.guardar_bruto:
                destino = RAIZ / "bruto" / "termo_de_embargo.csv.gz"
                destino.parent.mkdir(parents=True, exist_ok=True)
                with open(csv_local, "rb") as a, gzip.open(destino, "wb", compresslevel=6) as b:
                    shutil.copyfileobj(a, b)
                log(f"  bruto guardado em {destino.name} (ATENCAO: traz CPF completo; a pasta bruto/ fica fora do git e do Drive)")
            log(f"== fim em {time.time() - t0:.0f} s: GRAVADO ({stats['inseridos']:,} versoes inseridas, {stats['reabertos']:,} reabertas, "
                f"{stats['ausentes']:,} fechadas por ausencia)".replace(",", "."))
            return 0


if __name__ == "__main__":
    sys.exit(main())
