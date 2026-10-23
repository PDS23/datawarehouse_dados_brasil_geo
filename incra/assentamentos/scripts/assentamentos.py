"""Assentamentos rurais do INCRA (poligonos de projetos de assentamento) -> vetorial.incra_assentamentos.

Coleta direto do WFS publico do Acervo Fundiario do INCRA (sem login), uma camada por UF (27), guarda o
GML bruto, grava de forma idempotente e registra a execucao em catalogo.cargas.

Uso (no conteiner etl, a partir de infra/):
  docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl incra/assentamentos/scripts/assentamentos.py [opcoes]

  OPCOES: --ufs PR,SC (so estas UFs; padrao: as 27) | --simular (transacao desfeita: nada e gravado nem guardado) | --sem-bruto

Regras (ver incra/assentamentos/config.yaml e LEIAME_assentamentos.md):
  - uma linha por POLIGONO (gid do INCRA); o mesmo projeto (cd_sipra) pode ter varios poligonos;
  - cobertura nacional = as 27 UFs; UF que o servidor nao entrega NAO e escondida: o aviso lista as UFs que
    faltaram e o script termina com codigo 3 (parcial). O servidor do INCRA falha de forma persistente em algumas UFs;
  - nunca apaga: poligono que sumiu do servidor continua na tabela com visto_em antigo e e listado no aviso;
  - reexecutar nao duplica nem reescreve o que nao mudou.
"""
import argparse
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import yaml

from dwlib import bruto, db, wfs
from dwlib.catalogo import Carga, registrar_dataset
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # incra/assentamentos
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
SRID = CFG["srid_gravado"]
CAIXA = CFG["caixa_brasil"]
COLUNAS = ["gid_incra", "cd_sipra", "nome_projeto", "municipio", "id_estado_camada", "area_declarada_ha", "area_calc_ha",
           "capacidade_familias", "num_familias", "fase", "data_criacao", "forma_obtencao", "data_obtencao",
           "geom", "id_fonte", "importado_em", "visto_em"]
CHAVE = ["gid_incra"]
ATUALIZAR = [c for c in COLUNAS if c not in CHAVE]
COMPARAR = [c for c in ATUALIZAR if c not in ("importado_em", "visto_em")]
PAR = re.compile(r"(-?\d+\.\d+) (-?\d+\.\d+)")


def log(*a):
    print(*a, flush=True)


def data(txt):
    return datetime.strptime(txt, "%d/%m/%Y").date() if txt else None


def numero(txt):
    return float(txt.replace(",", ".")) if txt else None


def inteiro(txt):
    return int(float(txt.replace(",", "."))) if txt else None


def dentro_do_brasil(ewkt):
    """Todos os vertices dentro da caixa do Brasil (conferencia de sanidade: pega eixo trocado e lixo)."""
    for x, y in PAR.findall(ewkt):
        x, y = float(x), float(y)
        if not (CAIXA["lon_min"] <= x <= CAIXA["lon_max"] and CAIXA["lat_min"] <= y <= CAIXA["lat_max"]):
            return False
    return True


def converter(props, ewkt, id_estado_camada, fonte, hoje):
    c = CFG["campos"]
    inv = {dest: props.get(orig) for orig, dest in c.items()}
    if not inv["gid_incra"] or not inv["cd_sipra"]:
        raise ValueError(f"feicao sem gid/cd_sipra: {props}")
    return (int(inv["gid_incra"]), inv["cd_sipra"], inv["nome_projeto"], inv["municipio"], id_estado_camada,
            numero(inv["area_declarada_ha"]), numero(inv["area_calc_ha"]), inteiro(inv["capacidade_familias"]),
            inteiro(inv["num_familias"]), inteiro(inv["fase"]), data(inv["data_criacao"]), inv["forma_obtencao"],
            data(inv["data_obtencao"]), ewkt, fonte, hoje, hoje)


CAMPOS_SHP = {"nome_proje": "nome_projeto", "area_hecta": "area_hectare_declarada", "num_famili": "num_familias",
              "data_de_cr": "data_de_criacao", "forma_obte": "forma_obtencao", "data_obten": "data_obtencao",
              "area_calc_": "area_calc_ha"}


def ler_zip(caminho):
    """Shapefile do Acervo Fundiario (export_shp.py, baixado manualmente com login gov.br) -> [(props no padrao do WFS, ewkt)].

    O shapefile nao traz o gid do INCRA: gid_incra vira um numero NEGATIVO derivado de cd_sipra + geometria
    (estavel enquanto o poligono nao mudar; nao colide com os gids reais, que sao positivos)."""
    import zlib
    from pyogrio.raw import read
    meta, _, geoms, campos = read(f"zip://{caminho}")
    nomes = [str(n) for n in meta["fields"]]
    itens, usados = [], set()
    for i, wkb in enumerate(geoms):
        props = {}
        for j, n in enumerate(nomes):
            v = campos[j][i]
            v = None if v is None or (isinstance(v, float) and v != v) else str(v).strip()
            props[CAMPOS_SHP.get(n, n)] = v or None
        base = f"{props['cd_sipra']}|".encode() + bytes(wkb)
        n = 0                                           # o INCRA publica poligonos identicos repetidos: conta a ocorrencia
        while (gid := -(zlib.crc32(base + str(n).encode()) % 2147483647 + 1)) in usados:
            n += 1
        usados.add(gid)
        props["gid"] = str(gid)
        itens.append((props, wfs.ewkt_de_wkb(bytes(wkb), SRID)))
    return itens


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="Assentamentos do INCRA (WFS publico) -> vetorial.incra_assentamentos")
    ap.add_argument("--ufs", help="siglas separadas por virgula (padrao: as 27)")
    ap.add_argument("--zip", action="append", default=[], metavar="UF=ARQUIVO",
                    help="usa o shapefile (zip) baixado do Acervo Fundiario no lugar do WFS para essa UF, ex.: "
                         "--zip PA=incra/assentamentos/bruto/export_shp/assentamento_pa.zip (repetivel)")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--sem-bruto", action="store_true")
    args = ap.parse_args()
    zips = {}
    for item in args.zip:
        uf_z, _, arq = item.partition("=")
        zips[uf_z.strip().upper()] = str(Path(arq.strip()).resolve())
    if args.zip and not args.ufs:
        args.ufs = ",".join(zips)                       # --zip sozinho carrega so as UFs dos zips
    ufs = [u.strip().upper() for u in args.ufs.split(",")] if args.ufs else CFG["ufs"]
    desconhecidas = [u for u in ufs if u not in CFG["ufs"]]
    if desconhecidas:
        raise SystemExit(f"UFs desconhecidas: {desconhecidas}")

    conn = db.conectar()
    fonte = db.id_fonte(conn, CFG["fonte"])
    with conn.cursor() as cur:
        cur.execute("SELECT sigla_uf, id_estado FROM dim.estados")
        id_estado = dict(cur.fetchall())

    falhas, sumiram, fora_do_brasil, por_uf = {}, {}, [], {}
    with Carga(conn, "incra_assentamentos", dataset="vetorial.incra_assentamentos", parametros=vars(args), simular=args.simular) as carga:
        hoje, t0 = date.today(), time.time()
        log(f"== coleta: {len(ufs)} UF(s) no WFS do INCRA ({CFG['url_wfs']})")
        for uf in ufs:
            tema = CFG["tema_por_uf"].format(uf=uf.lower())
            dados = None
            try:
                if uf in zips:
                    itens = ler_zip(zips[uf])
                    log(f"  {uf}: lido do shapefile {zips[uf]}")
                else:
                    dados = wfs.baixar(CFG["url_wfs"], tema)
                    esperado = dados.count(b"<gml:featureMember>")
                    itens = list(wfs.feicoes(dados, SRID))
                    if esperado == 0 or len(itens) != esperado:
                        raise wfs.ErroWFS(f"{len(itens)} feicoes lidas de {esperado} no GML")
            except Exception as e:
                falhas[uf] = f"{type(e).__name__}: {e}"[:200]
                log(f"  {uf}: FALHOU ({falhas[uf]}). Alternativa: baixar o shapefile em {CFG['url_export_shp']} "
                    f"(login gov.br; selectshp=assent, selectuf={uf}) e rodar com --zip {uf}=<arquivo.zip>")
                continue
            carga.lidas += len(itens)
            linhas, rejeitadas = [], 0
            for props, ewkt in itens:
                if ewkt is None or not dentro_do_brasil(ewkt):
                    rejeitadas += 1
                    fora_do_brasil.append((uf, props.get("gid"), props.get("nome_projeto")))
                    continue
                linhas.append(converter(props, ewkt, id_estado[uf], fonte, hoje))
            ins, atu = db.upsert(conn, "vetorial", "incra_assentamentos", COLUNAS, linhas, CHAVE, ATUALIZAR, comparar=COMPARAR)
            with conn.cursor() as cur:
                cur.execute("UPDATE vetorial.incra_assentamentos SET visto_em = %s WHERE gid_incra = ANY(%s) AND visto_em < %s",
                            (hoje, [l[0] for l in linhas], hoje))
                # UF onde o poligono esta (a camada do INCRA e a jurisdicao da superintendencia: a do DF tem GO e MG).
                # So para linhas novas ou alteradas hoje; fora de qualquer estado, vale a UF da camada.
                cur.execute("UPDATE vetorial.incra_assentamentos a SET id_estado = coalesce("
                            "(SELECT e.id_estado FROM dim.estados e WHERE ST_Intersects(e.geom, ST_PointOnSurface(a.geom)) "
                            "ORDER BY e.id_estado LIMIT 1), a.id_estado_camada) "
                            "WHERE a.id_estado_camada = %s AND (a.id_estado IS NULL OR a.importado_em = %s)",
                            (id_estado[uf], hoje))
                cur.execute("SELECT gid_incra, cd_sipra FROM vetorial.incra_assentamentos WHERE id_estado_camada = %s AND visto_em < %s",
                            (id_estado[uf], hoje))
                sumiu = cur.fetchall()
            if sumiu:
                sumiram[uf] = sumiu
            carga.inseridas += ins
            carga.atualizadas += atu
            carga.rejeitadas += rejeitadas
            por_uf[uf] = len(linhas)
            if not args.simular:
                conn.commit()
                if not args.sem_bruto and dados is not None:
                    bruto.salvar_bytes_gz(RAIZ / "bruto" / "wfs_incra", f"assentamentos_{uf.lower()}", dados,
                                          fonte=f"{CFG['url_wfs']}?tema={tema}&service=WFS&version=1.1.0&request=GetFeature&typename={tema}&srsName=EPSG:4326",
                                          filtro="resposta completa do servidor, sem alteracao",
                                          extra={"uf": uf, "feicoes": len(itens)})
            log(f"  {uf}: {len(itens)} poligonos; {ins} novos, {atu} atualizados, {rejeitadas} rejeitados")

        log("== conferencia")
        with conn.cursor() as cur:
            cur.execute("SELECT count(*), count(*) FILTER (WHERE NOT ST_IsValid(geom)), count(*) FILTER (WHERE ST_IsEmpty(geom)) "
                        "FROM vetorial.incra_assentamentos")
            total, invalidas, vazias = cur.fetchone()
        log(f"  tabela: {total} poligonos; geometrias invalidas: {invalidas}; vazias: {vazias}")
        if invalidas:
            carga.avisos.append(f"{invalidas} geometria(s) invalida(s) na tabela (nao corrigidas: ver LEIAME)")
        if fora_do_brasil:
            aviso = f"{len(fora_do_brasil)} poligono(s) fora da caixa do Brasil ou sem geometria (NAO gravados): {fora_do_brasil[:5]}"
            log("  AVISO:", aviso)
            carga.avisos.append(aviso)
        if sumiram:
            aviso = f"poligonos que sumiram do servidor (mantidos, visto_em antigo): " + "; ".join(f"{u}: {len(v)}" for u, v in sumiram.items())
            log("  AVISO:", aviso)
            carga.avisos.append(aviso)
        if falhas:
            aviso = f"{len(falhas)} UF(s) NAO coletada(s), cobertura incompleta: " + "; ".join(f"{u} ({m})" for u, m in falhas.items())
            log("  AVISO:", aviso)
            carga.avisos.append(aviso)
        else:
            log(f"  as {len(ufs)} UFs foram coletadas")

        if not args.simular and por_uf:
            registrar_dataset(conn, "INCRA - Assentamentos rurais (projetos de assentamento)", "vetorial.incra_assentamentos", fonte,
                              ano_referencia=hoje.year, licenca=CFG["licenca"], tipo="vetor",
                              observacoes="Poligonos do WFS publico do Acervo Fundiario (uma camada por UF). Um projeto (cd_sipra) pode ter varios "
                                          "poligonos; area_declarada_ha nao se soma por linha. Ver incra/assentamentos/LEIAME_assentamentos.md."
                                          + (f" UFs NAO coletadas na ultima carga: {', '.join(falhas)}." if falhas else ""))
            conn.commit()
        log(f"== fim: {carga.lidas} poligonos lidos; {carga.inseridas} novos, {carga.atualizadas} atualizados, "
            f"{carga.rejeitadas} rejeitados; {time.time() - t0:.0f} s")
        if args.simular:
            conn.rollback()
            log("SIMULACAO: nada foi gravado.")
    conn.close()
    return 3 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
