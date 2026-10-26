"""Gera o diagrama do banco (entidade-relacionamento) a partir do catalogo do PostgreSQL: nunca desatualiza, e so refaz.

Saidas em infra/diagrama/:
  modelo_banco.svg              imagem do esquema (tabelas, colunas principais, chaves estrangeiras), para README/portfolio
  modelo_banco_pagina.html      pagina interativa (clique numa tabela para ver todas as colunas), a mesma do artefato publicado
  modelo_banco.json             os dados lidos do catalogo (tabelas, colunas, contagens, chaves)

Uso (no conteiner etl, a partir de infra/):
  docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl infra/scripts/gerar_diagrama_banco.py

So le: metadados do catalogo e a contagem de linhas (count(*); se o papel nao puder ler a tabela, usa a estimativa do catalogo).
Regra de desenho: id_fonte -> dim.fontes existe em quase toda tabela (rastreabilidade) e NAO e desenhada como linha, para o desenho
nao virar um novelo; aparece como a etiqueta 'fonte' na linha da coluna. O layout (quem fica em qual coluna) e fixo, em LAYOUT.
"""
import html
import json
import re
from pathlib import Path

from dwlib import db

SAIDA = Path(__file__).resolve().parents[1] / "diagrama"
SCHEMAS = ("dim", "vetorial", "tabular", "resultados", "catalogo")
LARGURA, ALT_TITULO, ALT_LINHA, ALT_RODAPE, GAP = 290, 44, 18, 20, 38
MAX_LINHAS = 9
LARGURA_CATALOGO = 2500
# colunas do layout: x e as tabelas de cima para baixo
LAYOUT = [
    (40, ["dim.cultura", "dim.cultura_equivalencia", "dim.malha_anterior"]),
    (400, ["tabular.ibge_pam", "tabular.ibge_censoagro2017_estab_lavoura_perm", "tabular.sidra_valor"]),
    (760, ["dim.fontes", "dim.estados", "dim.municipios", "dim.biomas"]),
    (1120, ["vetorial.prodes_desmatamento", "vetorial.sicar_imoveis", "vetorial.incra_assentamentos", "vetorial.mapbiomas_alerta", "vetorial.funai_terras_indigenas", "vetorial.deter_alertas", "vetorial.ibama_embargos"]),
    (1480, ["resultados.prodes_municipio", "vetorial.v_prodes_municipio", "vetorial.ibge_dominios_naturais", "vetorial.ibge_regioes_naturais"]),
    # camada generica do SIDRA (dimensoes que dizem o que cada id de tabular.sidra_valor significa)
    (1840, ["dim.sidra_pesquisa", "dim.sidra_tabela", "dim.sidra_tabela_eixo", "dim.sidra_classificacao", "dim.sidra_categoria"]),
    (2200, ["dim.sidra_variavel", "dim.unidade", "dim.sidra_situacao", "catalogo.sidra_recorte"]),
]
CATALOGO = ["catalogo.datasets", "catalogo.cargas", "catalogo.coletas", "catalogo.coletas_duplicados", "catalogo.mapa_colunas",
            "catalogo.v_ultima_coleta"]
ESPELHOS = {"vetorial.sicar_imoveis", "vetorial.prodes_desmatamento", "vetorial.mapbiomas_alerta", "vetorial.funai_terras_indigenas", "vetorial.deter_alertas", "vetorial.ibama_embargos", "tabular.sidra_valor"}      # versionados (vigente_desde / vigente_ate)
VIEWS_USAM = {"vetorial.v_prodes_municipio": ["resultados.prodes_municipio", "vetorial.prodes_desmatamento"],
              "tabular.ibge_censoagro2017_estab_lavoura_perm": ["tabular.sidra_valor"],
              "catalogo.v_ultima_coleta": ["catalogo.coletas"]}
SQL = """
SELECT c.oid, n.nspname, c.relname, c.relkind, greatest(c.reltuples, 0)::bigint, obj_description(c.oid, 'pg_class'),
       CASE WHEN c.relkind IN ('r','p') THEN pg_total_relation_size(c.oid) END
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY(%s) AND c.relkind IN ('r','p','v','m') ORDER BY 2, 3"""
SQL_COLS = """
SELECT a.attrelid, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
       EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = a.attrelid AND k.contype = 'p' AND a.attnum = ANY (k.conkey)),
       col_description(a.attrelid, a.attnum)
FROM pg_attribute a WHERE a.attrelid = ANY(%s) AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attrelid, a.attnum"""
SQL_FKS = """
SELECT conrelid::regclass::text, (SELECT string_agg(attname, ',') FROM pg_attribute WHERE attrelid = conrelid AND attnum = ANY (conkey)),
       confrelid::regclass::text, (SELECT string_agg(attname, ',') FROM pg_attribute WHERE attrelid = confrelid AND attnum = ANY (confkey))
FROM pg_constraint WHERE contype = 'f' AND connamespace IN (SELECT oid FROM pg_namespace WHERE nspname = ANY(%s))"""


def ler_catalogo():
    conn = db.conectar()
    cur = conn.cursor()
    cur.execute(SQL, (list(SCHEMAS),))
    linhas = cur.fetchall()
    tabelas = {}
    for oid, sch, nome, tipo, est, coment, bytes_ in linhas:
        tabelas[f"{sch}.{nome}"] = {"id": f"{sch}.{nome}", "sch": sch, "nome": nome, "view": tipo in ("v", "m"), "linhas": int(est),
                                    "exato": False, "bytes": bytes_, "coment": coment, "cols": [], "oid": oid}
    cur.execute(SQL_COLS, ([t["oid"] for t in tabelas.values()],))
    por_oid = {t["oid"]: t for t in tabelas.values()}
    for oid, n, tipo, nn, pk, coment in cur.fetchall():
        por_oid[oid]["cols"].append({"n": n, "t": tipo, "nn": nn, "pk": pk, "c": coment})
    cur.execute(SQL_FKS, (list(SCHEMAS),))
    fks = [{"de": a, "col": b, "para": c, "colpara": d} for a, b, c, d in cur.fetchall()]
    conn.rollback()
    for t in tabelas.values():                                   # contagem exata; se nao puder ler, fica a estimativa
        if t["view"]:
            continue
        try:
            cur.execute(f'SELECT count(*) FROM "{t["sch"]}"."{t["nome"]}"')
            t["linhas"], t["exato"] = cur.fetchone()[0], True
        except Exception:
            conn.rollback()
    cur.execute("SELECT count(*) FROM catalogo.datasets WHERE tipo = 'raster'")
    rasters = cur.fetchone()[0]
    conn.close()
    for t in tabelas.values():
        t.pop("oid")
    return tabelas, fks, rasters


def fmt(n):
    return f"{n:,}".replace(",", ".")


def tamanho(b):
    if not b:
        return ""
    for un, d in (("GB", 1 << 30), ("MB", 1 << 20), ("kB", 1 << 10)):
        if b >= d:
            v = b / d
            return (f"{v:.1f}".replace(".", ",") if v < 10 else f"{v:.0f}") + " " + un
    return f"{b} B"


def escolher_colunas(t, fk_cols):
    cols = t["cols"]
    if len(cols) <= MAX_LINHAS:
        return cols, 0
    prio = lambda c: (0 if c["pk"] else 1 if c["n"] in fk_cols else 2 if c["t"].startswith("geometry") else
                      3 if c["n"] in ("vigente_desde", "vigente_ate") else 9)
    base = [c for c in cols if prio(c) < 9]
    resto = [c for c in cols if prio(c) == 9]
    escolha = (base + resto)[:MAX_LINHAS]
    escolha = [c for c in cols if c in escolha]                   # ordem original
    return escolha, len(cols) - len(escolha)


def altura(t, fk_cols):
    cols, extra = escolher_colunas(t, fk_cols)
    return ALT_TITULO + len(cols) * ALT_LINHA + (ALT_RODAPE if extra else 8)


def montar(tabelas, fks, rasters):
    fk_por_tabela = {}
    for f in fks:
        fk_por_tabela.setdefault(f["de"], set()).update(f["col"].split(","))
    pos = {}
    for x, nomes in LAYOUT:
        y = 70
        for nome in nomes:
            if nome in tabelas:
                pos[nome] = [x, y]
                y += altura(tabelas[nome], fk_por_tabela.get(nome, set())) + GAP
    y_base = max(pos[n][1] + altura(tabelas[n], fk_por_tabela.get(n, set())) for n in pos) + 70
    # catalogo em fileiras ao longo da base, quebrando quando passa da largura
    x, y, maxh = 40, y_base + 34, 0
    for nome in [n for n in CATALOGO if n in tabelas]:
        if x + LARGURA > LARGURA_CATALOGO:
            x, y, maxh = 40, y + maxh + GAP, 0
        pos[nome] = [x, y]
        maxh = max(maxh, altura(tabelas[nome], fk_por_tabela.get(nome, set())))
        x += LARGURA + 36
    H = max(p[1] + altura(tabelas[n], fk_por_tabela.get(n, set())) for n, p in pos.items()) + 60
    W = max(x for x, _ in LAYOUT) + LARGURA + 40
    partes, linhas_y = [], {}
    # --- caixas
    caixas = []
    for nome, (x0, y0) in pos.items():
        t = tabelas[nome]
        cols, extra = escolher_colunas(t, fk_por_tabela.get(nome, set()))
        h = altura(t, fk_por_tabela.get(nome, set()))
        cls = "tab " + t["sch"] + (" vw" if t["view"] else "") + (" esp" if nome in ESPELHOS else "")
        g = [f'<g class="{cls}" data-t="{nome}" transform="translate({x0},{y0})" tabindex="0" role="button" aria-label="{nome}">',
             f'<rect class="corpo" width="{LARGURA}" height="{h}" rx="6"/>',
             f'<path class="cab" d="M0 6a6 6 0 0 1 6-6h{LARGURA - 12}a6 6 0 0 1 6 6v{ALT_TITULO - 6}H0z"/>',
             f'<text class="nome" x="12" y="18">{html.escape(t["nome"])}</text>']
        sub = (("view · " if t["view"] else "") + (f"{fmt(t['linhas'])} linhas" if not t["view"] else "") +
               (" · " + tamanho(t["bytes"]) if t["bytes"] else ""))
        g.append(f'<text class="sub" x="12" y="35">{html.escape(t["sch"])} · {html.escape(sub)}</text>')
        if nome in ESPELHOS:
            g.append(f'<text class="selo" x="{LARGURA - 10}" y="18" text-anchor="end">espelho versionado</text>')
        for i, c in enumerate(cols):
            yy = ALT_TITULO + i * ALT_LINHA
            linhas_y[(nome, c["n"])] = y0 + yy + ALT_LINHA / 2
            if i % 2:
                g.append(f'<rect class="zebra" y="{yy}" width="{LARGURA}" height="{ALT_LINHA}"/>')
            marca = "PK" if c["pk"] else ("FK" if c["n"] in fk_por_tabela.get(nome, set()) and c["n"] != "id_fonte" else
                                           ("fonte" if c["n"] == "id_fonte" else ("geo" if c["t"].startswith("geometry") else "")))
            if marca:
                g.append(f'<text class="m {marca}" x="10" y="{yy + 13}">{marca}</text>')
            g.append(f'<text class="col{" pk" if c["pk"] else ""}" x="44" y="{yy + 13}">{html.escape(c["n"])}</text>')
            tipo = re.sub(r"geometry\((\w+),(\d+)\)", r"\1 \2", c["t"]).replace("character varying", "varchar") \
                     .replace("timestamp with time zone", "timestamptz").replace("double precision", "float8")
            tipo = tipo if len(tipo) <= 18 else tipo[:17] + "…"
            g.append(f'<text class="tp" x="{LARGURA - 10}" y="{yy + 13}" text-anchor="end">{html.escape(tipo)}</text>')
            g.append(f'<rect class="hit" data-c="{html.escape(c["n"])}" y="{yy}" width="{LARGURA}" height="{ALT_LINHA}"/>')
        if extra:
            g.append(f'<text class="mais" x="12" y="{ALT_TITULO + len(cols) * ALT_LINHA + 14}">+ {extra} colunas (clique para ver todas)</text>')
        g.append("</g>")
        caixas.append("\n".join(g))
    # --- ligacoes (atras das caixas)
    arestas = []
    for f in fks:
        if f["de"] not in pos or f["para"] not in pos or f["col"] == "id_fonte":
            continue
        c0, c1 = f["col"].split(",")[0], f["colpara"].split(",")[0]
        xa, xb = pos[f["de"]][0], pos[f["para"]][0]
        ya = linhas_y.get((f["de"], c0), pos[f["de"]][1] + 30)
        yb = linhas_y.get((f["para"], c1), pos[f["para"]][1] + 30)
        if xa < xb:
            sx, tx = xa + LARGURA, xb
        elif xa > xb:
            sx, tx = xa, xb + LARGURA
        else:
            sx, tx = xa + LARGURA, xb + LARGURA
        dx = max(abs(tx - sx) * 0.5, 40) * (1 if tx >= sx else -1)
        if xa == xb:
            dx = 60
        d = f"M{sx} {ya} C{sx + dx} {ya} {tx - dx if xa != xb else tx + 60} {yb} {tx} {yb}"
        arestas.append(f'<g class="lig" data-de="{f["de"]}" data-para="{f["para"]}"><path d="{d}"/>'
                       f'<circle cx="{sx}" cy="{ya}" r="3.2"/><circle class="alvo" cx="{tx}" cy="{yb}" r="3.2"/>'
                       f'<title>{f["de"]}.{f["col"]} → {f["para"]}.{f["colpara"]}</title></g>')
    for v, usa in VIEWS_USAM.items():
        for u in usa:
            if v in pos and u in pos:
                xa, xb = pos[v][0], pos[u][0]
                sx = xa if xb < xa else xa + LARGURA
                tx = xb + LARGURA if xb < xa else xb
                ya, yb = pos[v][1] + 24, pos[u][1] + 24
                if xa == xb:
                    sx = tx = xa + LARGURA
                    d = f"M{sx} {ya} C{sx + 50} {ya} {tx + 50} {yb} {tx} {yb}"
                else:
                    dx = max(abs(tx - sx) * 0.5, 40) * (1 if tx >= sx else -1)
                    d = f"M{sx} {ya} C{sx + dx} {ya} {tx - dx} {yb} {tx} {yb}"
                arestas.append(f'<g class="lig vw" data-de="{v}" data-para="{u}"><path d="{d}"/><title>view {v} le {u}</title></g>')
    faixa = (f'<text class="faixa" x="40" y="{y_base + 20}">CATÁLOGO · proveniência, controle e rastreabilidade (de onde veio cada dado, quando e quanto)</text>'
             f'<line class="faixa-l" x1="40" x2="{W - 40}" y1="{y_base + 4}" y2="{y_base + 4}"/>')
    cabeca = ('<text class="faixa" x="40" y="32">DIMENSÕES (vocabulário comum, tracejado = view) · TABULARES · GEOMETRIAS · RESULTADOS</text>')
    ultima = max((n for n in CATALOGO if n in pos), key=lambda n: (pos[n][1], pos[n][0]))   # ultima caixa do catalogo (ultima fileira)
    nx, ny = pos[ultima][0] + LARGURA + 40, pos[ultima][1] + 16
    nota = (f'<g transform="translate({nx},{ny})"><text class="nota" x="0" y="0">Fora do banco: {rasters} rasters (MapBiomas, TOPODATA)</text>'
            f'<text class="nota" x="0" y="16">ficam em arquivo COG e são servidos pelo GeoServer;</text>'
            f'<text class="nota" x="0" y="32">só o catálogo.datasets os registra.</text></g>')
    svg = (f'<svg viewBox="0 0 {W} {H}" width="{W}" role="img" aria-label="Esquema do banco data_warehouse: dimensões, geometrias, tabelas, resultados e catálogo, com as chaves estrangeiras">'
           f'<defs><marker id="seta" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" class="seta"/></marker></defs>'
           + cabeca + faixa + "\n".join(arestas) + "\n" + "\n".join(caixas) + nota + "</svg>")
    return svg, W, H


CSS_SVG = """
.tab .hit{fill:transparent}
.tab .corpo{fill:var(--caixa);stroke:var(--linha);stroke-width:1.2}
.tab .cab{fill:var(--c)} .tab.vw .corpo{stroke-dasharray:5 3}
.tab.dim{--c:var(--dim)} .tab.vetorial{--c:var(--vet)} .tab.tabular{--c:var(--tab)} .tab.resultados{--c:var(--res)} .tab.catalogo{--c:var(--cat)}
.tab .nome{font:600 13px var(--mono);fill:#fff} .tab .sub{font:11px var(--sans);fill:#fff;opacity:.85}
.tab .selo{font:600 10px var(--sans);fill:#fff;opacity:.95}
.tab .zebra{fill:var(--zebra)} .tab .col{font:12px var(--mono);fill:var(--texto)} .tab .col.pk{font-weight:700}
.tab .tp{font:10.5px var(--mono);fill:var(--suave)} .tab .mais{font:italic 11px var(--sans);fill:var(--suave)}
.tab .m{font:700 9px var(--sans);letter-spacing:.04em} .tab .m.PK{fill:var(--pk)} .tab .m.FK{fill:var(--fk)} .tab .m.fonte{fill:var(--suave)} .tab .m.geo{fill:var(--geo)}
.tab{cursor:pointer} .tab:hover .corpo,.tab:focus .corpo,.tab.sel .corpo{stroke:var(--c);stroke-width:2.4}
.lig path{fill:none;stroke:var(--lig);stroke-width:1.4;opacity:.55} .lig circle{fill:var(--lig);opacity:.8} .lig.vw path{stroke-dasharray:4 3}
.lig.on path{stroke:var(--destaque);stroke-width:2.4;opacity:1} .lig.on circle{fill:var(--destaque);opacity:1}
.lig.off{opacity:.12}
.faixa{font:700 12px var(--sans);letter-spacing:.06em;fill:var(--suave)} .faixa-l{stroke:var(--linha);stroke-width:1}
.nota{font:12px var(--sans);fill:var(--suave)}
"""
PALETA_CLARA = ("--caixa:#ffffff;--linha:#b9c2cc;--zebra:#f3f6f9;--texto:#1c2733;--suave:#5f6f80;--lig:#4b6a88;--destaque:#d9480f;"
                "--dim:#0f766e;--vet:#2f7d32;--tab:#b45309;--res:#6d28d9;--cat:#475569;--pk:#b7791f;--fk:#1d4ed8;--geo:#2f7d32;"
                "--mono:Consolas,'Courier New',monospace;--sans:'Segoe UI',Arial,sans-serif;")


def pagina(svg, dados):
    dados_js = json.dumps(dados, ensure_ascii=False)
    return f"""<title>Esquema do Banco</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
/* Esquema do data warehouse. Layout: o diagrama em largura total, o painel de detalhe embaixo; tintas por schema (dim, vetorial, tabular, resultados, catalogo). */
:root{{--bg:#f6f8fa;--fg:#1c2733;--suave:#5f6f80;--caixa:#ffffff;--linha:#c5cdd6;--zebra:#f3f6f9;--texto:#1c2733;--lig:#4b6a88;--destaque:#d9480f;
--dim:#0f766e;--vet:#2f7d32;--tab:#b45309;--res:#6d28d9;--cat:#475569;--pk:#b7791f;--fk:#1d4ed8;--geo:#2f7d32;--painel:#ffffff;
--mono:Consolas,'Courier New',monospace;--sans:'Segoe UI',system-ui,Arial,sans-serif}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#10161d;--fg:#e6edf3;--suave:#9aa9b8;--caixa:#18212b;--linha:#33414f;--zebra:#1d2832;--texto:#e6edf3;--lig:#7ea1c4;--destaque:#ff8a4c;
--dim:#14a39a;--vet:#4caf50;--tab:#e08a2e;--res:#9d6bff;--cat:#7d8da0;--pk:#e3b341;--fk:#6ea8ff;--geo:#5fd068;--painel:#18212b;color-scheme:dark}}}}
:root[data-theme="dark"]{{--bg:#10161d;--fg:#e6edf3;--suave:#9aa9b8;--caixa:#18212b;--linha:#33414f;--zebra:#1d2832;--texto:#e6edf3;--lig:#7ea1c4;--destaque:#ff8a4c;
--dim:#14a39a;--vet:#4caf50;--tab:#e08a2e;--res:#9d6bff;--cat:#7d8da0;--pk:#e3b341;--fk:#6ea8ff;--geo:#5fd068;--painel:#18212b;color-scheme:dark}}
body{{background:var(--bg);color:var(--fg);font-family:var(--sans);margin:0;padding-block:20px 40px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));line-height:1.5}}
main{{max-width:1900px;margin:0 auto;display:flex;flex-direction:column;gap:20px}}
h1{{font-size:28px;line-height:1.15;margin:0;text-wrap:balance}} .sub{{color:var(--suave);margin:4px 0 0;max-width:80ch}}
.fig{{overflow-x:auto;background:var(--bg);border:1px solid var(--linha);border-radius:8px;padding:8px}}
.fig svg{{display:block;height:auto}}
{CSS_SVG}
.legenda{{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:13px;color:var(--suave);align-items:center}}
.legenda span.chip{{display:inline-flex;align-items:center;gap:6px}} .legenda i{{width:12px;height:12px;border-radius:3px;display:inline-block;background:var(--c)}}
.grade{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}} .grade>*{{min-width:0}}
.painel{{background:var(--painel);border:1px solid var(--linha);border-radius:8px;padding:14px 16px}}
.painel h2{{font-size:15px;margin:0 0 8px;letter-spacing:.02em}} .painel p,.painel li{{font-size:14px}} .painel ul{{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:4px}}
#detalhe table{{border-collapse:collapse;font:12.5px var(--mono);width:100%}} #detalhe td,#detalhe th{{padding:3px 8px;border-bottom:1px solid var(--linha);text-align:left;vertical-align:top}}
#detalhe th{{font:600 11px var(--sans);color:var(--suave);letter-spacing:.05em;text-transform:uppercase}} .tw{{overflow-x:auto}}
.tag{{font:700 10px var(--sans);letter-spacing:.04em;padding:1px 5px;border-radius:3px;background:var(--zebra);color:var(--suave)}}
code{{font-family:var(--mono);font-size:.92em}}
#tip{{position:fixed;z-index:10;max-width:340px;background:var(--painel);color:var(--fg);border:1px solid var(--linha);border-left:3px solid var(--destaque);border-radius:6px;padding:8px 10px;
box-shadow:0 4px 14px rgba(0,0,0,.22);font:13px/1.4 var(--sans);pointer-events:none}}
#tip b{{font:600 12.5px var(--mono)}} #tip .t{{font:11px var(--mono);color:var(--suave);margin-left:6px}} #tip p{{margin:4px 0 0}} #tip .fk{{margin-top:4px;font:11.5px var(--mono);color:var(--fk)}} #tip .sem{{color:var(--suave);font-style:italic}}
</style>
<main>
<header><h1>Esquema do banco data_warehouse</h1>
<p class="sub">Tabelas, colunas principais e chaves estrangeiras, lidos direto do catálogo do PostgreSQL. Passe o mouse numa coluna para ver o que ela é e de onde vem; clique numa tabela para ver todas as colunas e as ligações dela.</p></header>
<div class="legenda" aria-label="Legenda">
<span class="chip"><i style="--c:var(--dim)"></i>dim · dimensões</span><span class="chip"><i style="--c:var(--vet)"></i>vetorial · geometrias</span>
<span class="chip"><i style="--c:var(--tab)"></i>tabular</span><span class="chip"><i style="--c:var(--res)"></i>resultados · derivados</span><span class="chip"><i style="--c:var(--cat)"></i>catálogo</span>
<span class="chip"><b style="color:var(--pk)">PK</b> chave primária</span><span class="chip"><b style="color:var(--fk)">FK</b> chave estrangeira (linha)</span>
<span class="chip"><b style="color:var(--suave)">fonte</b> id_fonte → dim.fontes (em quase toda tabela, sem linha)</span><span class="chip"><b style="color:var(--geo)">geo</b> geometria</span>
<span class="chip">tracejado = view</span></div>
<figure class="fig" style="margin:0"><div class="rolar" id="figura">{svg}</div></figure>
<div class="grade">
<section class="painel" id="detalhe" aria-live="polite"><h2>Detalhe da tabela</h2><p style="color:var(--suave)">Clique numa tabela do diagrama.</p></section>
<section class="painel"><h2>Como ler o esquema</h2><ul>
<li><b>Espelhos versionados</b> (<code>sicar_imoveis</code>, <code>prodes_desmatamento</code>, <code>mapbiomas_alerta</code>, <code>sidra_valor</code>): cada registro tem versões (<code>vigente_desde</code>, <code>vigente_ate</code>); vigente = <code>vigente_ate IS NULL</code>.</li>
<li><b>Camada genérica do SIDRA</b>: <code>sidra_valor</code> guarda todos os valores (uma partição por tabela do SIDRA) só com ids; <code>sidra_tabela_eixo</code> diz que classificação cada <code>id_cat1..6</code> representa em cada tabela, e <code>sidra_categoria</code> traz o nome (e, nas faixas de área, os limites em ha). O Censo (<code>ibge_censoagro2017_estab_lavoura_perm</code>) é uma view tipada sobre ela.</li>
<li><b>Dimensões</b> dão o vocabulário comum (estados, municípios, biomas, culturas, fontes); as tabelas de dado apontam para elas por chave.</li>
<li><b>Resultados</b> (<code>prodes_municipio</code>) são derivados e guardam o <code>id</code> da versão usada; as views mostram só o vigente.</li>
<li><b>Catálogo</b> registra cada carga (<code>cargas</code>), coleta (<code>coletas</code>, com a edição da fonte), dataset e o mapa de colunas (<code>mapa_colunas</code>: nome na fonte × nome no banco).</li>
</ul></section></div>
</main>
<div id="tip" role="tooltip" hidden></div>
<script>
const D = {dados_js};
const T = Object.fromEntries(D.tabelas.map(t => [t.id, t]));
const fig = document.getElementById('figura'), det = document.getElementById('detalhe');
const esc = s => String(s ?? '').replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]));
const fmt = n => n.toLocaleString('pt-BR');
function destacar(id) {{
  fig.querySelectorAll('.lig').forEach(l => {{
    const liga = id && (l.dataset.de === id || l.dataset.para === id);
    l.classList.toggle('on', !!liga); l.classList.toggle('off', !!id && !liga);
  }});
  fig.querySelectorAll('.tab').forEach(g => g.classList.toggle('sel', g.dataset.t === id));
}}
function mostrar(id) {{
  const t = T[id]; if (!t) return;
  const fks = D.fks.filter(f => f.de === id), entra = D.fks.filter(f => f.para === id && f.col !== 'id_fonte');
  const fkc = Object.fromEntries(fks.map(f => [f.col, f.para + '.' + f.colpara]));
  let h = `<h2>${{esc(t.id)}} ${{t.view ? '<span class="tag">view</span>' : ''}}</h2>`;
  h += `<p style="margin:0 0 8px;color:var(--suave)">${{t.view ? 'View' : fmt(t.linhas) + ' linhas'}}${{t.bytes ? ' · ' + (t.bytes / 1073741824 >= 1 ? (t.bytes / 1073741824).toFixed(1) + ' GB' : Math.round(t.bytes / 1048576) + ' MB') : ''}}</p>`;
  if (t.coment) h += `<p style="margin:0 0 8px">${{esc(t.coment)}}</p>`;
  h += '<div class="tw"><table><tr><th>coluna</th><th>tipo</th><th></th><th>o que é · de onde vem</th></tr>';
  for (const c of t.cols) {{
    const m = c.pk ? '<span class="tag">PK</span>' : (fkc[c.n] ? `<span class="tag">FK → ${{esc(fkc[c.n])}}</span>` : '');
    h += `<tr><td>${{esc(c.n)}}</td><td>${{esc(c.t)}}</td><td>${{m}}</td><td style="font-family:var(--sans)">${{esc(c.c)}}</td></tr>`;
  }}
  h += '</table></div>';
  if (entra.length) h += `<p style="margin:10px 0 0;color:var(--suave)">Referenciada por: ${{entra.map(f => esc(f.de) + '.' + esc(f.col)).join(', ')}}</p>`;
  det.innerHTML = h; det.dataset.sel = id; destacar(id);
}}
const tip = document.getElementById('tip');
function dica(e) {{
  const h = e.target.closest && e.target.closest('.hit');
  const g = h && h.parentNode, t = g && T[g.dataset.t], c = t && t.cols.find(x => x.n === h.dataset.c);
  if (!c) {{ tip.hidden = true; return; }}
  const fk = D.fks.find(f => f.de === t.id && f.col.split(',').includes(c.n) && f.col !== 'id_fonte');
  tip.innerHTML = `<b>${{esc(c.n)}}</b><span class="t">${{esc(c.t)}}${{c.pk ? ' · PK' : ''}}</span>` +
    (c.c ? `<p>${{esc(c.c)}}</p>` : '<p class="sem">sem descrição ainda</p>') +
    (fk ? `<div class="fk">→ ${{esc(fk.para)}}.${{esc(fk.colpara)}}</div>` : '');
  tip.hidden = false;
  const w = tip.offsetWidth, hh = tip.offsetHeight;
  let x = e.clientX + 16, y = e.clientY + 18;
  if (x + w > window.innerWidth - 8) x = Math.max(8, e.clientX - w - 16);
  if (y + hh > window.innerHeight - 8) y = Math.max(8, e.clientY - hh - 14);
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}}
fig.addEventListener('mousemove', dica);
fig.addEventListener('mouseleave', () => {{ tip.hidden = true; }});
fig.querySelectorAll('.tab').forEach(g => {{
  g.addEventListener('click', () => mostrar(g.dataset.t));
  g.addEventListener('keydown', e => {{ if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); mostrar(g.dataset.t); }} }});
  g.addEventListener('mouseenter', () => destacar(g.dataset.t));
  g.addEventListener('mouseleave', () => destacar(det.dataset.sel || null));
}});
</script>
"""


def main():
    tabelas, fks, rasters = ler_catalogo()
    SAIDA.mkdir(parents=True, exist_ok=True)
    svg, W, H = montar(tabelas, fks, rasters)
    dados = {"tabelas": [{k: v for k, v in t.items() if k != "exato"} for t in tabelas.values()], "fks": fks, "rasters": rasters}
    (SAIDA / "modelo_banco.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    estatico = svg.replace("<defs>", f'<style>svg{{{PALETA_CLARA}background:#f6f8fa}}{CSS_SVG}</style><defs>', 1)
    estatico = estatico.replace('<svg viewBox', '<svg xmlns="http://www.w3.org/2000/svg" viewBox', 1)
    (SAIDA / "modelo_banco.svg").write_text(estatico, encoding="utf-8")
    (SAIDA / "modelo_banco_pagina.html").write_text(pagina(svg, dados), encoding="utf-8")
    print(f"{len(tabelas)} tabelas/views, {len(fks)} chaves estrangeiras, SVG {W}x{H} -> {SAIDA}")


if __name__ == "__main__":
    main()
