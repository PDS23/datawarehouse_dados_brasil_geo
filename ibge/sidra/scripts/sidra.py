"""SIDRA (IBGE) -> camada genérica tabular.sidra_valor. Um pipeline para qualquer tabela do SIDRA configurada em config.yaml.

SOB DEMANDA: só carrega o recorte pedido (uma tabela, as categorias escolhidas, os períodos pedidos).

Uso (a partir da raiz do repositório):
  .\\infra\\scripts\\dw.ps1 etl ibge/sidra/scripts/sidra.py --tabela 6956 <o que fazer> [opções]

  O QUE FAZER (exatamente um):
    --listar                      mostra as categorias da classificação "pedido" e o que já está carregado (não grava nada)
    --cat 227=4961,laranja        carrega estas categorias da classificação 227 (código SIDRA ou slug); repita --cat se a tabela
                                  tiver mais de uma classificação "pedido"
    (nenhum dos dois)             só em tabela SEM classificação "pedido": carrega o recorte fixado no config.yaml
  OPÇÕES: --periodos 2017 | --nivel n6|n3|n1 | --simular | --sem-bruto | --aceitar-queda

Regras de gravação (ver ibge/sidra/LEIAME_sidra.md):
  - ids em vez de texto: variável, categoria, unidade e situação vêm de dim.sidra_*; local por id_municipio/id_estado;
  - espelho versionado: valor novo entra; valor que mudou fecha a versão antiga e insere a nova; valor que sumiu do recorte
    tem a versão fechada; valor que volta idêntico à última versão fechada é reaberto;
  - '-' (zero) e '...' (não se aplica) não geram linha (salvo tabela com guardar_simbolos); 'X' (sigilo) vira valor NULL + situação;
  - município fora de dim.municipios não é descartado em silêncio: é contado e listado;
  - confere a soma dos municípios com o total do Brasil em cada célula.
"""
import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

from dwlib import bruto, db, sidra
from dwlib.catalogo import Carga, registrar_dataset
from dwlib.sinais import tratar_sigterm

RAIZ = Path(__file__).resolve().parents[1]               # ibge/sidra
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
NIVEIS = {"n1": 1, "n3": 3, "n6": 6}
SITUACAO = {"-": 1, "X": 2, "...": 3, "..": 4}           # dim.sidra_situacao
CATS = [f"id_cat{i}" for i in range(1, 7)]
COLUNAS_STAGE = ["periodo", "nivel", "id_municipio", "id_estado", "id_variavel", "c1", "c2", "c3", "c4", "c5", "c6",
                 "valor", "id_situacao", "id_unidade"]
# A chave natural da versão vigente (ids ausentes valem 0 no stage e COALESCE(...,0) na tabela, como no índice único)
JUNCAO = ("v.periodo = s.periodo AND v.nivel = s.nivel AND COALESCE(v.id_municipio, 0) = s.id_municipio "
          "AND COALESCE(v.id_estado, 0) = s.id_estado AND v.id_variavel = s.id_variavel "
          + " ".join(f"AND COALESCE(v.id_cat{i}, 0) = s.c{i}" for i in range(1, 7)))


def log(*a):
    print(*a, flush=True)


def slug(nome):
    return re.sub(r"[^a-z0-9]+", "_", sidra.normaliza(nome)).strip("_")


def numero_br(txt):
    return float(txt.replace(".", "").replace(",", "."))


def faixa(nome):
    """(limite_inferior, limite_superior) em ha a partir do nome do grupo de área do IBGE; None onde não se aplica."""
    if nome.strip().lower() == "produtor sem área":
        return None, None
    m = re.fullmatch(r"(?:De|Mais de) ([\d.,]+) a menos de ([\d.,]+) ha", nome.strip())
    if m:
        return numero_br(m.group(1)), numero_br(m.group(2))
    m = re.fullmatch(r"De ([\d.,]+) ha e mais", nome.strip())
    if m:
        return numero_br(m.group(1)), None
    raise ValueError(f"grupo de área em formato desconhecido: {nome!r}")


# --------------------------------------------------------------------------- leitura do SIDRA
def enumerar(tab, nivel_n1="n1"):
    """Total do Brasil de todas as categorias de todas as classificações, para descobrir categorias, variáveis e unidades.
    Devolve ({posicao: {codigo: nome}}, {variavel: (nome, id_unidade, nome_unidade)})."""
    classes = {c["codigo"]: ("all" if c["filtro"] != "fixa" else c["categorias"]) for c in tab["classificacoes"]}
    regs = sidra.valores_cubo(tab["id"], nivel_n1, tab["variaveis"], tab["periodos"], classes)
    cats = {k: {} for k in range(len(tab["classificacoes"]))}
    variaveis = {}
    for r in regs:
        for k in cats:
            cats[k][r[f"D{4 + k}C"]] = r[f"D{4 + k}N"].strip()
        variaveis.setdefault(r["D2C"], (r["D2N"].strip(), int(r["MC"]), r["MN"].strip()))
    return cats, variaveis


# --------------------------------------------------------------------------- dimensões
def gravar_dimensoes(conn, tab, fonte, cats, variaveis, nomes_class):
    """Cadastra pesquisa, tabela, classificações, eixos, unidades, variáveis e categorias. Devolve {(posicao, codigo): id_categoria}."""
    with conn.cursor() as cur:
        p = tab["pesquisa"]
        cur.execute("INSERT INTO dim.sidra_pesquisa (codigo, nome) VALUES (%s, %s) ON CONFLICT (codigo) DO UPDATE SET nome = EXCLUDED.nome "
                    "WHERE dim.sidra_pesquisa.nome IS DISTINCT FROM EXCLUDED.nome", (p["codigo"], p["nome"]))
        cur.execute("SELECT id_pesquisa FROM dim.sidra_pesquisa WHERE codigo = %s", (p["codigo"],))
        id_pesquisa = cur.fetchone()[0]
        cur.execute("INSERT INTO dim.sidra_tabela (id_tabela, id_pesquisa, nome, periodicidade, id_fonte) VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (id_tabela) DO UPDATE SET id_pesquisa = EXCLUDED.id_pesquisa, nome = EXCLUDED.nome, "
                    "periodicidade = EXCLUDED.periodicidade, id_fonte = EXCLUDED.id_fonte "
                    "WHERE (dim.sidra_tabela.id_pesquisa, dim.sidra_tabela.nome, dim.sidra_tabela.periodicidade, dim.sidra_tabela.id_fonte) "
                    "IS DISTINCT FROM (EXCLUDED.id_pesquisa, EXCLUDED.nome, EXCLUDED.periodicidade, EXCLUDED.id_fonte)",
                    (tab["id"], id_pesquisa, tab["nome"], tab.get("periodicidade"), fonte))
        unidades = {}
        for nome, id_un, nome_un in variaveis.values():
            unidades[id_un] = nome_un
        for id_un, nome_un in unidades.items():
            cur.execute("INSERT INTO dim.unidade (id_unidade, nome) VALUES (%s, %s) ON CONFLICT (id_unidade) DO UPDATE SET nome = EXCLUDED.nome "
                        "WHERE dim.unidade.nome IS DISTINCT FROM EXCLUDED.nome", (id_un, nome_un))
        for cod, (nome, id_un, _) in variaveis.items():
            cur.execute("INSERT INTO dim.sidra_variavel (id_variavel, nome, id_unidade) VALUES (%s, %s, %s) ON CONFLICT (id_variavel) DO UPDATE "
                        "SET nome = EXCLUDED.nome, id_unidade = EXCLUDED.id_unidade WHERE (dim.sidra_variavel.nome, dim.sidra_variavel.id_unidade) "
                        "IS DISTINCT FROM (EXCLUDED.nome, EXCLUDED.id_unidade)", (int(cod), nome, id_un))
        ids = {}
        for k, c in enumerate(tab["classificacoes"]):
            id_class = int(c["codigo"])
            cur.execute("INSERT INTO dim.sidra_classificacao (id_classificacao, nome) VALUES (%s, %s) ON CONFLICT (id_classificacao) DO UPDATE "
                        "SET nome = EXCLUDED.nome WHERE dim.sidra_classificacao.nome IS DISTINCT FROM EXCLUDED.nome", (id_class, nomes_class[k]))
            cur.execute("INSERT INTO dim.sidra_tabela_eixo (id_tabela, posicao, id_classificacao) VALUES (%s, %s, %s) "
                        "ON CONFLICT (id_tabela, posicao) DO UPDATE SET id_classificacao = EXCLUDED.id_classificacao "
                        "WHERE dim.sidra_tabela_eixo.id_classificacao IS DISTINCT FROM EXCLUDED.id_classificacao", (tab["id"], k + 1, id_class))
            itens = [(cod, nome) for cod, nome in cats[k].items() if cod not in c.get("excluir", [])]
            if c.get("faixas"):
                lim = {cod: faixa(nome) for cod, nome in itens}
                itens.sort(key=lambda i: (-1.0 if lim[i[0]][0] is None else lim[i[0]][0], lim[i[0]][1] if lim[i[0]][1] is not None else 1e18))
            else:
                lim = {}
                itens.sort(key=lambda i: int(i[0]))
            for ordem, (cod, nome) in enumerate(itens, 1):
                inf, sup = lim.get(cod, (None, None))
                cur.execute("INSERT INTO dim.sidra_categoria (id_classificacao, codigo_sidra, nome, limite_inferior, limite_superior, ordem) "
                            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id_classificacao, codigo_sidra) DO UPDATE SET nome = EXCLUDED.nome, "
                            "limite_inferior = EXCLUDED.limite_inferior, limite_superior = EXCLUDED.limite_superior, ordem = EXCLUDED.ordem "
                            "WHERE (dim.sidra_categoria.nome, dim.sidra_categoria.limite_inferior, dim.sidra_categoria.limite_superior, "
                            "dim.sidra_categoria.ordem) IS DISTINCT FROM (EXCLUDED.nome, EXCLUDED.limite_inferior, EXCLUDED.limite_superior, EXCLUDED.ordem)",
                            (id_class, int(cod), nome, inf, sup, ordem))
            cur.execute("SELECT codigo_sidra, id_categoria FROM dim.sidra_categoria WHERE id_classificacao = %s", (id_class,))
            for codigo, id_cat in cur.fetchall():
                ids[(k, str(codigo))] = id_cat
    return ids


# --------------------------------------------------------------------------- transformação
def converte(txt, guardar_simbolos):
    """(valor, id_situacao, gravar?) para o texto do SIDRA."""
    t = (txt or "").strip()
    if t in SITUACAO:
        sit = SITUACAO[t]
        if t == "X":
            return None, sit, True
        if not guardar_simbolos:
            return None, sit, False
        return (0.0 if t == "-" else None), sit, True
    v = sidra.parse_valor(t)
    return v, None, v is not None


def transformar(registros, tab, escolhidas, ids_cat, nivel, municipios_dim, estados_dim, guardar_simbolos):
    """Registros da API -> (linhas do stage, somas por célula, sigilos por célula, rejeitados)."""
    n_cl = len(tab["classificacoes"])
    permitido = [set(escolhidas[k]) for k in range(n_cl)]
    linhas, rejeitados = {}, []
    somas, sigilos = defaultdict(float), defaultdict(int)
    for r in registros:
        cods = []
        for k in range(n_cl):
            cod = r[f"D{4 + k}C"]
            if cod not in permitido[k]:      # a ordem das dimensões vem da tabela: se o IBGE mudar, para aqui em vez de gravar errado
                raise RuntimeError(f"layout inesperado da tabela {tab['id']}: categoria {cod} fora do pedido na posição {k + 1}: {r}")
            cods.append(cod)
        if r["D3C"] not in tab["periodos"]:
            raise RuntimeError(f"período inesperado {r['D3C']} na tabela {tab['id']}")
        valor, sit, gravar = converte(r["V"], guardar_simbolos)
        celula = (r["D3C"], r["D2C"], tuple(cods))
        if valor is not None:
            somas[celula] += valor
        if sit == SITUACAO["X"]:
            sigilos[celula] += 1
        if not gravar:
            continue
        mun = est = 0
        if nivel == 6:
            mun = int(r["D1C"])
            if mun not in municipios_dim:
                rejeitados.append(mun)
                continue
        elif nivel == 3:
            est = int(r["D1C"])
            if est not in estados_dim:
                rejeitados.append(est)
                continue
        cats6 = [ids_cat[(k, cods[k])] for k in range(n_cl)] + [0] * (6 - n_cl)
        chave = (int(r["D3C"]), nivel, mun, est, int(r["D2C"]), *cats6)
        linhas[chave] = chave + (valor, sit, int(r["MC"]))
    return list(linhas.values()), somas, sigilos, rejeitados


def reconciliar(conn, tab, nivel, escolhidas_ids, variaveis, periodos, linhas, id_carga, hoje, max_queda, aceitar_queda):
    """Compara o stage com os valores vigentes do recorte e grava. Devolve (novos, fechados, reabertos, vigentes_antes)."""
    escopo = ["v.id_tabela = %(t)s", "v.vigente_ate IS NULL", "v.nivel = %(nivel)s", "v.periodo = ANY(%(periodos)s)",
              "v.id_variavel = ANY(%(variaveis)s)"]
    par = {"t": tab["id"], "nivel": nivel, "periodos": [int(p) for p in periodos], "variaveis": [int(v) for v in variaveis],
           "hoje": hoje, "carga": id_carga}
    for k, ids in escolhidas_ids.items():
        escopo.append(f"v.id_cat{k + 1} = ANY(%(cat{k + 1})s)")
        par[f"cat{k + 1}"] = list(ids)
    escopo = " AND ".join(escopo)
    with conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE _sidra_stage (periodo integer, nivel smallint, id_municipio integer, id_estado smallint, "
                    "id_variavel integer, c1 integer, c2 integer, c3 integer, c4 integer, c5 integer, c6 integer, valor numeric, "
                    "id_situacao smallint, id_unidade integer) ON COMMIT DROP")
        with cur.copy(f"COPY _sidra_stage ({', '.join(COLUNAS_STAGE)}) FROM STDIN") as copia:
            for linha in linhas:
                copia.write_row(linha)
        cur.execute(f"SELECT count(*) FROM tabular.sidra_valor v WHERE {escopo}", par)
        vigentes_antes = cur.fetchone()[0]
        if vigentes_antes and len(linhas) < (1 - max_queda) * vigentes_antes and not aceitar_queda:
            raise RuntimeError(f"trava de segurança: o recorte tem {vigentes_antes} valores vigentes e a coleta trouxe só {len(linhas)} "
                               f"(queda de mais de {max_queda:.0%}). Se for real, rode com --aceitar-queda.")
        # 1) fecha o que mudou ou sumiu
        cur.execute(f"UPDATE tabular.sidra_valor v SET vigente_ate = %(hoje)s WHERE {escopo} AND NOT EXISTS ("
                    f"SELECT 1 FROM _sidra_stage s WHERE {JUNCAO} AND s.valor IS NOT DISTINCT FROM v.valor "
                    f"AND s.id_situacao IS NOT DISTINCT FROM v.id_situacao)", par)
        fechados = cur.rowcount
        # 2) reabre o que voltou idêntico à última versão fechada
        cur.execute(f"""WITH ultimas AS (
                            SELECT DISTINCT ON (v.periodo, v.nivel, COALESCE(v.id_municipio, 0), COALESCE(v.id_estado, 0), v.id_variavel,
                                   COALESCE(v.id_cat1, 0), COALESCE(v.id_cat2, 0), COALESCE(v.id_cat3, 0), COALESCE(v.id_cat4, 0),
                                   COALESCE(v.id_cat5, 0), COALESCE(v.id_cat6, 0))
                                   v.id, v.valor, v.id_situacao, s.valor AS s_valor, s.id_situacao AS s_sit
                            FROM tabular.sidra_valor v JOIN _sidra_stage s ON {JUNCAO}
                            WHERE v.id_tabela = %(t)s AND v.vigente_ate IS NOT NULL
                              AND NOT EXISTS (SELECT 1 FROM tabular.sidra_valor w WHERE w.id_tabela = %(t)s AND w.vigente_ate IS NULL
                                              AND w.periodo = v.periodo AND w.nivel = v.nivel
                                              AND COALESCE(w.id_municipio, 0) = COALESCE(v.id_municipio, 0)
                                              AND COALESCE(w.id_estado, 0) = COALESCE(v.id_estado, 0) AND w.id_variavel = v.id_variavel
                                              AND COALESCE(w.id_cat1, 0) = COALESCE(v.id_cat1, 0) AND COALESCE(w.id_cat2, 0) = COALESCE(v.id_cat2, 0)
                                              AND COALESCE(w.id_cat3, 0) = COALESCE(v.id_cat3, 0) AND COALESCE(w.id_cat4, 0) = COALESCE(v.id_cat4, 0)
                                              AND COALESCE(w.id_cat5, 0) = COALESCE(v.id_cat5, 0) AND COALESCE(w.id_cat6, 0) = COALESCE(v.id_cat6, 0))
                            ORDER BY v.periodo, v.nivel, COALESCE(v.id_municipio, 0), COALESCE(v.id_estado, 0), v.id_variavel,
                                     COALESCE(v.id_cat1, 0), COALESCE(v.id_cat2, 0), COALESCE(v.id_cat3, 0), COALESCE(v.id_cat4, 0),
                                     COALESCE(v.id_cat5, 0), COALESCE(v.id_cat6, 0), v.vigente_ate DESC, v.id DESC)
                        UPDATE tabular.sidra_valor t SET vigente_ate = NULL, reaberto_em = %(hoje)s FROM ultimas u
                        WHERE t.id_tabela = %(t)s AND t.id = u.id AND u.valor IS NOT DISTINCT FROM u.s_valor
                          AND u.id_situacao IS NOT DISTINCT FROM u.s_sit""", par)
        reabertos = cur.rowcount
        # 3) insere o que não tem versão vigente
        cur.execute(f"""INSERT INTO tabular.sidra_valor (id_tabela, periodo, nivel, id_municipio, id_estado, id_variavel, id_cat1, id_cat2,
                            id_cat3, id_cat4, id_cat5, id_cat6, valor, id_situacao, id_unidade, id_carga, vigente_desde)
                        SELECT %(t)s, s.periodo, s.nivel, NULLIF(s.id_municipio, 0), NULLIF(s.id_estado, 0), s.id_variavel,
                               NULLIF(s.c1, 0), NULLIF(s.c2, 0), NULLIF(s.c3, 0), NULLIF(s.c4, 0), NULLIF(s.c5, 0), NULLIF(s.c6, 0),
                               s.valor, s.id_situacao, s.id_unidade, %(carga)s, %(hoje)s
                        FROM _sidra_stage s
                        WHERE NOT EXISTS (SELECT 1 FROM tabular.sidra_valor v WHERE v.id_tabela = %(t)s AND v.vigente_ate IS NULL AND {JUNCAO})""",
                    par)
        novos = cur.rowcount
    return novos, fechados, reabertos, vigentes_antes


# --------------------------------------------------------------------------- principal
def resolver_pedido(tab, cats, args_cat):
    """{posicao: [códigos]} das categorias a carregar em cada classificação."""
    pedidas = {}
    for item in args_cat or []:
        cl, _, resto = item.partition("=")
        pedidas[cl.strip()] = [x.strip() for x in resto.split(",") if x.strip()]
    escolhidas = {}
    for k, c in enumerate(tab["classificacoes"]):
        excl = set(c.get("excluir", []))
        validas = {cod: nome for cod, nome in cats[k].items() if cod not in excl}
        if c["filtro"] == "fixa":
            escolhidas[k] = list(c["categorias"])
        elif c["filtro"] == "todas":
            escolhidas[k] = list(validas)
        else:
            if c["codigo"] not in pedidas:
                raise SystemExit(f"a classificação c{c['codigo']} é 'pedido': informe --cat {c['codigo']}=<códigos ou slugs> (use --listar)")
            por_slug = {slug(n): cod for cod, n in validas.items()}
            sel = [por_slug.get(x, x) for x in pedidas[c["codigo"]]]
            desconhecidos = [x for x in sel if x not in validas]
            if desconhecidos:
                raise SystemExit(f"categorias desconhecidas em c{c['codigo']}: {desconhecidos} (use --listar)")
            escolhidas[k] = sel
    sobra = set(pedidas) - {c["codigo"] for c in tab["classificacoes"] if c["filtro"] == "pedido"}
    if sobra:
        raise SystemExit(f"--cat para classificação que não é 'pedido' nesta tabela: {sorted(sobra)}")
    return escolhidas


def listar(conn, tab, cats):
    with conn.cursor() as cur:
        for k, c in enumerate(tab["classificacoes"]):
            if c["filtro"] != "pedido":
                continue
            cur.execute(f"SELECT g.codigo_sidra, count(*) FROM tabular.sidra_valor v JOIN dim.sidra_categoria g ON g.id_categoria = v.id_cat{k + 1} "
                        "WHERE v.id_tabela = %s AND v.vigente_ate IS NULL GROUP BY 1", (tab["id"],))
            carregado = {str(a): b for a, b in cur.fetchall()}
            excl = set(c.get("excluir", []))
            itens = sorted(((cod, n) for cod, n in cats[k].items() if cod not in excl), key=lambda i: int(i[0]))
            log(f"tabela {tab['id']}, classificação c{c['codigo']}: {len(itens)} categorias")
            log(f"{'código':>8}  {'slug':<42} {'nome':<50} carregado")
            for cod, nome in itens:
                n = carregado.get(cod)
                log(f"{cod:>8}  {slug(nome):<42} {nome:<50} {f'{n:,} valores'.replace(',', '.') if n else '-'}")
            log(f"carregadas: {len(carregado)}")


def main():
    tratar_sigterm()
    ap = argparse.ArgumentParser(description="SIDRA (IBGE) -> tabular.sidra_valor, sob demanda")
    ap.add_argument("--tabela", required=True, help="número da tabela no SIDRA (deve constar em config.yaml)")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--cat", action="append", help="classificação=códigos ou slugs (ex.: 227=4961,laranja)")
    ap.add_argument("--periodos", help="períodos separados por vírgula (padrão: os da config)")
    ap.add_argument("--nivel", choices=list(NIVEIS), help="padrão: nivel_padrao da config")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--sem-bruto", action="store_true")
    ap.add_argument("--aceitar-queda", action="store_true")
    args = ap.parse_args()
    if args.tabela not in CFG["tabelas"]:
        raise SystemExit(f"tabela {args.tabela} não consta em ibge/sidra/config.yaml (tabelas: {sorted(CFG['tabelas'])})")
    tab = dict(CFG["tabelas"][args.tabela], id=int(args.tabela))
    tem_pedido = any(c["filtro"] == "pedido" for c in tab["classificacoes"])
    if args.listar and args.cat:
        ap.error("informe --cat ou --listar, não os dois")
    if not args.listar and tem_pedido and not args.cat:
        ap.error("informe --cat (ou --listar): nada é carregado por padrão")
    # tabela sem classificação "pedido" (ex.: 9515, sem classificações): o recorte inteiro já está fixado no config.yaml
    if args.periodos:
        tab["periodos"] = [p.strip() for p in args.periodos.split(",")]
    nivel_n = args.nivel or tab["nivel_padrao"]
    nivel = NIVEIS[nivel_n]

    conn = db.conectar()
    fonte = db.id_fonte(conn, CFG["fonte"])
    cats, variaveis = enumerar(tab)
    if args.listar:
        listar(conn, tab, cats)
        conn.close()
        return
    escolhidas = resolver_pedido(tab, cats, args.cat)
    primeiras = {c["codigo"]: escolhidas[k][0] for k, c in enumerate(tab["classificacoes"])}
    cab = sidra.cabecalho(tab["id"], tab["variaveis"][0], tab["periodos"][0], primeiras)
    nomes_class = [cab[f"D{4 + k}N"].strip() for k in range(len(tab["classificacoes"]))]
    classes_pedido = {c["codigo"]: escolhidas[k] for k, c in enumerate(tab["classificacoes"])}
    guardar = tab.get("guardar_simbolos", False)

    with Carga(conn, f"sidra_{args.tabela}", dataset="tabular.sidra_valor", parametros=vars(args), simular=args.simular) as carga:
        hoje, t0 = date.today(), time.time()
        log(f"== 1) dimensões da tabela {tab['id']} a partir das categorias do SIDRA")
        ids_cat = gravar_dimensoes(conn, tab, fonte, cats, variaveis, nomes_class)
        with conn.cursor() as cur:
            cur.execute("SELECT catalogo.sidra_garantir_particao(%s)", (tab["id"],))
            log(f"  partição: {cur.fetchone()[0]}")
            cur.execute("SELECT id_municipio FROM dim.municipios")
            municipios_dim = {r[0] for r in cur.fetchall()}
            cur.execute("SELECT id_estado FROM dim.estados")
            estados_dim = {r[0] for r in cur.fetchall()}
        if not args.simular:
            conn.commit()

        log(f"== 2) total do Brasil do recorte, para validar a soma dos {'municípios' if nivel == 6 else 'estados'}")
        nac = {}
        if nivel in (6, 3):
            for r in sidra.valores_cubo(tab["id"], "n1", tab["variaveis"], tab["periodos"], classes_pedido):
                nac[(r["D3C"], r["D2C"], tuple(r[f"D{4 + k}C"] for k in range(len(tab["classificacoes"]))))] = sidra.parse_valor(r["V"])

        log(f"== 3) coleta no nível {nivel_n} ({len(tab['variaveis'])} variável(is), {len(tab['periodos'])} período(s); a API é lenta, é normal demorar)")
        regs = sidra.valores_cubo(tab["id"], nivel_n, tab["variaveis"], tab["periodos"], classes_pedido)
        carga.lidas += len(regs)
        log(f"  {len(regs):,} valores lidos em {time.time() - t0:.0f} s".replace(",", "."))
        linhas, somas, sigilos, rejeitados = transformar(regs, tab, escolhidas, ids_cat, nivel, municipios_dim, estados_dim, guardar)

        log("== 4) reconciliação com o que já está no banco")
        escolhidas_ids = {k: [ids_cat[(k, c)] for c in cods] for k, cods in escolhidas.items()}
        id_carga = carga.id
        if id_carga is None:                 # simulação: tudo é desfeito no fim, só precisa de um id válido para a chave estrangeira
            with conn.cursor() as cur:
                cur.execute("SELECT min(id) FROM catalogo.cargas")
                id_carga = cur.fetchone()[0]
        novos, fechados, reabertos, antes = reconciliar(conn, tab, nivel, escolhidas_ids, tab["variaveis"], tab["periodos"], linhas, id_carga,
                                                       hoje, CFG["max_queda"], args.aceitar_queda)
        carga.inseridas += novos
        carga.atualizadas += fechados
        log(f"  vigentes antes: {antes:,}; no SIDRA agora: {len(linhas):,}; novas versões: {novos:,}; fechadas: {fechados:,}; reabertas: {reabertos:,}"
            .replace(",", "."))
        carga.rejeitadas += len(rejeitados)

        log("== 5) conferência")
        if rejeitados:
            aviso = f"{len(set(rejeitados))} território(s) do SIDRA fora das dimensões (linhas NÃO gravadas): {sorted(set(rejeitados))[:10]}"
            log("  AVISO:", aviso)
            carga.avisos.append(aviso)
        divergencias = []
        for celula, total in nac.items():
            if total is None:
                continue
            if abs(somas.get(celula, 0.0) - total) > 1e-6:
                divergencias.append((celula, somas.get(celula, 0.0), total, sigilos.get(celula, 0)))
        inesperadas = [d for d in divergencias if d[3] == 0]
        if inesperadas:
            aviso = f"{len(inesperadas)} divergência(s) entre a soma do recorte e o total do Brasil SEM sigilo que explique"
            log("  AVISO:", aviso)
            for celula, soma, total, _ in inesperadas[:12]:
                log(f"    {celula}: soma {soma:,.0f} x Brasil {total:,.0f}".replace(",", "."))
            carga.avisos.append(aviso)
        elif nac:
            log("  soma dos territórios = total do Brasil em todas as células sem sigilo")
        if divergencias:
            log(f"  {len(divergencias) - len(inesperadas)} célula(s) com soma abaixo do Brasil, explicadas por sigilo (X)")
        log(f"  células em sigilo (X): {sum(sigilos.values())}")

        if not args.simular:
            conn.execute("INSERT INTO catalogo.sidra_recorte (id_tabela, nivel, periodo_inicio, periodo_fim, filtros, linhas_lidas, linhas_gravadas, id_carga) "
                         "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)",
                         (tab["id"], nivel, int(min(tab["periodos"])), int(max(tab["periodos"])),
                          json.dumps({"classificacoes": classes_pedido, "variaveis": tab["variaveis"], "periodos": tab["periodos"]}),
                          len(regs), len(linhas), carga.id))
            registrar_dataset(conn, "IBGE - SIDRA (camada genérica de valores)", "tabular.sidra_valor", fonte,
                              licenca="Dados abertos do IBGE (citar a fonte); confirmar termos",
                              observacoes="Sob demanda: só os recortes pedidos (ver catalogo.sidra_recorte). Uma partição por tabela do SIDRA; ids em "
                                          "vez de texto (dim.sidra_*). Ver ibge/sidra/LEIAME_sidra.md.")
            conn.commit()
            if not args.sem_bruto:
                rotulo = "_".join(f"c{c['codigo']}-{'-'.join(escolhidas[k][:3])}{'+' if len(escolhidas[k]) > 3 else ''}"
                                  for k, c in enumerate(tab["classificacoes"]) if c["filtro"] == "pedido")
                guardados = [r for r in regs if r["V"] not in ("-", "...", "..", "")]
                destino, n = bruto.salvar_jsonl_gz(
                    RAIZ / "bruto" / f"sidra_{args.tabela}", f"{args.tabela}_{rotulo}_{nivel_n}", guardados,
                    fonte=f"https://apisidra.ibge.gov.br/values/t/{args.tabela}/{nivel_n}/all/v/{','.join(tab['variaveis'])}/p/{','.join(tab['periodos'])}",
                    filtro="células '-' (zero) e '...' (não se aplica) omitidas; 'X' (sigilo) mantidas; demais como a API devolveu",
                    extra={"classificacoes": classes_pedido})
                log(f"  bruto {destino.name}: {n} registros")
        log(f"== fim: {carga.lidas} valores lidos; {carga.inseridas} versões novas, {carga.atualizadas} fechadas; {time.time() - t0:.0f} s")
        if args.simular:
            conn.rollback()
            log("SIMULAÇÃO: nada foi gravado.")
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
