"""Ferramentas do servidor MCP de consulta: funções Python comuns, testáveis sem MCP (o servidor.py só as expõe para a IA).

Cada chamada abre UMA conexão nova como o papel consulta_ia, numa transação somente leitura que termina em ROLLBACK: nada do que a consulta
fizer (nem um set_config) sobrevive à chamada. Proteções do `consultar`, além do privilégio do papel (só SELECT, coluna a coluna):
  - o SQL é embrulhado como subconsulta (SELECT ... FROM (<sql>) AS _q LIMIT n) e enviado com parâmetro, pelo protocolo estendido do
    PostgreSQL, que só aceita um comando: "; DROP ..." ou "; SET ..." viram erro de sintaxe;
  - SET LOCAL statement_timeout a cada chamada; EXPLAIN antes, recusando custo acima do limite do config.yaml;
  - linhas e texto limitados; geometria resumida (tipo, área, comprimento, centroide) em vez do WKB;
  - avisos quando a consulta lê tabela versionada sem filtrar a versão, ou mede área em graus.
"""
import datetime as dt
import decimal
import fnmatch
import json
import os
import re
import time
import uuid
from pathlib import Path

import psycopg
import yaml
from psycopg import sql

RAIZ = Path(__file__).resolve().parents[3]
PASTA = RAIZ / "servicos" / "consulta_ia"
CFG = yaml.safe_load((PASTA / "config.yaml").read_text(encoding="utf-8"))
SCHEMAS = CFG["schemas"]
LIM = CFG["consulta"]
NOME_TABELA = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")


class ErroConsulta(Exception):
    """Erro com mensagem pensada para a IA ler e corrigir a consulta."""


# --------------------------------------------------------------------------------------------------------------------------------------
# conexão e registro

def conectar():
    senha = os.environ.get("PGPASSWORD")
    if not senha:
        raise ErroConsulta("PGPASSWORD vazio: no compose ele vem de CONSULTA_IA_PASSWORD (infra/.env).")
    return psycopg.connect(
        host=os.environ.get("PGHOST", "postgis"), port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "data_warehouse"), user=os.environ.get("PGUSER", CFG["papel"]),
        password=senha, connect_timeout=15, application_name="consulta_ia",
    )


def _abrir(cur, tempo_s=None):
    """Primeiros comandos de toda transação: somente leitura e com tempo limitado (vale só para esta transação)."""
    cur.execute("SET TRANSACTION READ ONLY")
    cur.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(f"{int(tempo_s or LIM['tempo_maximo_s'])}s")))


def _ler(consulta, params=None):
    """Consulta interna do servidor (catálogo): devolve lista de dicts."""
    with conectar() as conn, conn.cursor() as cur:
        _abrir(cur, 30)
        cur.execute(consulta, params)
        nomes = [d.name for d in cur.description]
        linhas = [dict(zip(nomes, r)) for r in cur.fetchall()]
        conn.rollback()
    return linhas


def registrar(ferramenta, argumentos, inicio, ok, erro=None, extra=None):
    """Uma linha JSONL por chamada em infra/logs/consulta_ia/AAAA-MM.jsonl. Falha ao gravar o log não derruba a ferramenta."""
    try:
        pasta = RAIZ / CFG["registro"]["pasta"]
        pasta.mkdir(parents=True, exist_ok=True)
        agora = dt.datetime.now().astimezone()
        linha = {"em": agora.isoformat(timespec="seconds"), "ferramenta": ferramenta, "argumentos": argumentos,
                 "ok": ok, "erro": erro, "tempo_ms": round((time.monotonic() - inicio) * 1000),
                 "origem": os.environ.get("CONSULTA_IA_ORIGEM", "local"), "usuario": os.environ.get("CONSULTA_IA_USUARIO")}
        linha.update(extra or {})
        with open(pasta / f"{agora:%Y-%m}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------------------------------------------------------------------
# valores para JSON

def _valor(v):
    if v is None or isinstance(v, (bool, int)):
        return v
    if isinstance(v, float):
        return v if v == v and abs(v) != float("inf") else str(v)
    if isinstance(v, decimal.Decimal):
        return float(v) if v.is_finite() else str(v)
    if isinstance(v, (dt.date, dt.datetime, dt.time)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, memoryview)):
        return f"<binário, {len(bytes(v))} bytes>"
    if isinstance(v, (dict, list)):
        texto = json.dumps(v, ensure_ascii=False, default=str)
        return v if len(texto) <= LIM["texto_maximo"] * 4 else texto[: LIM["texto_maximo"] * 4] + "… [cortado]"
    texto = str(v)
    return texto if len(texto) <= LIM["texto_maximo"] else texto[: LIM["texto_maximo"]] + f"… [cortado, {len(texto)} caracteres]"


# --------------------------------------------------------------------------------------------------------------------------------------
# retenção (infra/retencao.yaml) e datasets

def _retencao():
    try:
        r = yaml.safe_load((RAIZ / "infra" / "retencao.yaml").read_text(encoding="utf-8"))
    except OSError:
        return {}
    pad_rem, pad_sub = r.get("dias_removidas_padrao"), r.get("dias_substituidas_padrao")
    return {t["tabela"]: {"chave_da_versao": t.get("chave"),
                          "dias_guardando_versoes_substituidas": t.get("dias_substituidas", pad_sub),
                          "dias_guardando_registros_retirados": t.get("dias_removidas", pad_rem)}
            for t in r.get("tabelas", [])}


def listar_fontes():
    inicio = time.monotonic()
    try:
        linhas = _ler("""
            SELECT d.nome AS dataset, d.tipo, d.schema_tabela AS tabela, f.nome AS fonte, f.sigla, f.url AS url_fonte, d.licenca,
                   d.ano_referencia, d.data_importacao,
                   c.ultima AS ultima_coleta, c.primeira AS primeira_coleta_registrada, c.recortes AS recortes_coletados,
                   CASE WHEN d.cobertura IS NULL THEN NULL
                        ELSE round((ST_Area(d.cobertura::geography) / 10000)::numeric) END AS cobertura_ha,
                   CASE WHEN to_regclass(d.schema_tabela) IS NULL THEN NULL
                        ELSE (SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass(d.schema_tabela)) END AS linhas_estimadas_todas_versoes,
                   d.observacoes
            FROM catalogo.datasets d
            LEFT JOIN dim.fontes f USING (id_fonte)
            LEFT JOIN LATERAL (SELECT max(coletado_em) AS ultima, min(coletado_em) AS primeira, count(DISTINCT recorte) AS recortes
                               FROM catalogo.coletas c WHERE c.dataset = d.schema_tabela) c ON true
            ORDER BY d.tipo, d.nome, d.ano_referencia""")
        ret = _retencao()
        saida = []
        for l in linhas:
            item = {k: _valor(v) for k, v in l.items() if v is not None}
            if l["tipo"] == "raster":
                item["consultavel_por_sql"] = False
                item["nota"] = "raster fora do banco (arquivo/GeoServer): não dá para consultar por aqui"
            else:
                item["consultavel_por_sql"] = True
                item["cobertura"] = "Brasil (ou recorte descrito na documentação)" if l["cobertura_ha"] is None else "recorte (ver cobertura_ha)"
            if l["tabela"] in ret:
                item["retencao"] = ret[l["tabela"]]
            saida.append(item)
        registrar("listar_fontes", {}, inicio, True, extra={"n": len(saida)})
        return {"datasets": saida,
                "nota": "Datas de coleta em UTC. Detalhes de uma tabela: descrever_tabela. Metodologia e cobertura: ler_documentacao."}
    except psycopg.Error as e:
        registrar("listar_fontes", {}, inicio, False, str(e))
        raise ErroConsulta(f"falha ao ler o catálogo: {e}") from e


def listar_tabelas(schema=None):
    inicio = time.monotonic()
    if schema and schema not in SCHEMAS:
        raise ErroConsulta(f"schema '{schema}' fora do acesso; os liberados são: {', '.join(SCHEMAS)}")
    alvo = [schema] if schema else SCHEMAS
    linhas = _ler("""
        SELECT n.nspname || '.' || c.relname AS tabela,
               CASE c.relkind WHEN 'v' THEN 'view' WHEN 'm' THEN 'view materializada' ELSE 'tabela' END AS tipo,
               obj_description(c.oid, 'pg_class') AS descricao,
               CASE WHEN c.relkind IN ('r', 'p') THEN greatest(c.reltuples, 0)::bigint END AS linhas_estimadas,
               EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'vigente_ate' AND NOT a.attisdropped) AS versionada,
               EXISTS (SELECT 1 FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid
                       WHERE a.attrelid = c.oid AND t.typname IN ('geometry', 'geography') AND NOT a.attisdropped) AS espacial
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = ANY(%s) AND c.relkind IN ('r', 'p', 'v', 'm') AND NOT c.relispartition
          AND has_any_column_privilege(c.oid, 'SELECT')
        ORDER BY 1""", (alvo,))
    registrar("listar_tabelas", {"schema": schema}, inicio, True, extra={"n": len(linhas)})
    return {"tabelas": [{k: _valor(v) for k, v in l.items() if v is not None} for l in linhas],
            "nota": "Views v_* são o retrato vigente (sem dado pessoal) publicado no GeoServer; as tabelas trazem também as versões fechadas."}


def descrever_tabela(tabela):
    inicio = time.monotonic()
    tabela = (tabela or "").strip().lower()
    if not NOME_TABELA.match(tabela):
        raise ErroConsulta("informe a tabela como schema.nome (ex.: vetorial.sicar_imoveis); listar_tabelas mostra as disponíveis")
    if tabela.split(".")[0] not in SCHEMAS:
        raise ErroConsulta(f"schema fora do acesso; os liberados são: {', '.join(SCHEMAS)}")
    info = _ler("""
        SELECT c.oid::bigint AS oid, obj_description(c.oid, 'pg_class') AS descricao, c.relkind::text AS relkind,
               CASE WHEN c.relkind IN ('r', 'p') THEN greatest(c.reltuples, 0)::bigint END AS linhas_estimadas,
               has_any_column_privilege(c.oid, 'SELECT') AS visivel
        FROM pg_class c WHERE c.oid = to_regclass(%s)""", (tabela,))
    if not info or not info[0]["visivel"]:
        raise ErroConsulta(f"tabela {tabela} não existe ou não está liberada; listar_tabelas mostra as disponíveis")
    oid = info[0]["oid"]
    colunas = _ler("""
        SELECT a.attname AS coluna, format_type(a.atttypid, a.atttypmod) AS tipo, col_description(a.attrelid, a.attnum) AS descricao,
               has_column_privilege(a.attrelid, a.attnum, 'SELECT') AS visivel, a.attnotnull AS obrigatoria
        FROM pg_attribute a WHERE a.attrelid = %s::oid AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum""", (oid,))
    restricoes = _ler("""
        SELECT con.contype::text AS tipo, pg_get_constraintdef(con.oid) AS definicao
        FROM pg_constraint con WHERE con.conrelid = %s::oid AND con.contype IN ('p', 'u', 'f') ORDER BY con.contype""", (oid,))
    indices = _ler("""SELECT am.amname AS metodo, pg_get_indexdef(i.indexrelid) AS definicao
                      FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid JOIN pg_am am ON am.oid = ic.relam
                      WHERE i.indrelid = %s::oid ORDER BY 1""", (oid,))
    # Não dá para usar public.geometry_columns: ela só mostra tabelas com permissão de TABELA, e este papel tem permissão por coluna.
    # Tipo e SRID saem do modificador da própria coluna (geometry(MultiPolygon,4674)); sem modificador: Geometry e SRID 0.
    geoms = _ler("""SELECT a.attname AS coluna, t.typname AS tipo_coluna, postgis_typmod_type(a.atttypmod) AS tipo,
                           postgis_typmod_srid(a.atttypmod) AS srid
                    FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid
                    WHERE a.attrelid = %s::oid AND t.typname IN ('geometry', 'geography') AND a.attnum > 0 AND NOT a.attisdropped
                      AND has_column_privilege(a.attrelid, a.attnum, 'SELECT')""", (oid,))
    dataset = _ler("""SELECT d.nome, f.nome AS fonte, (SELECT max(coletado_em) FROM catalogo.coletas c WHERE c.dataset = d.schema_tabela) AS ultima_coleta
                      FROM catalogo.datasets d LEFT JOIN dim.fontes f USING (id_fonte) WHERE d.schema_tabela = %s""", (tabela,))
    visiveis = [c for c in colunas if c["visivel"]]
    ocultas = [c["coluna"] for c in colunas if not c["visivel"]]
    nomes = {"p": "chave primária", "u": "única", "f": "chave estrangeira"}
    saida = {
        "tabela": tabela, "descricao": info[0]["descricao"], "linhas_estimadas_todas_versoes": info[0]["linhas_estimadas"],
        "versionada": any(c["coluna"] == "vigente_ate" for c in colunas),
        "colunas": [{k: _valor(v) for k, v in c.items() if k != "visivel" and v is not None} for c in visiveis],
        "chaves": [{"tipo": nomes[r["tipo"]], "definicao": r["definicao"]} for r in restricoes],
        "indices": [{"metodo": r["metodo"], "definicao": r["definicao"]} for r in indices],
        "geometria": geoms,
    }
    if dataset:
        saida["dataset"] = {k: _valor(v) for k, v in dataset[0].items()}
    if ocultas:
        saida["colunas_ocultas"] = {"colunas": ocultas, "motivo": "dado pessoal (LGPD): não liberado para este acesso"}
    if saida["versionada"]:
        saida["versoes"] = ("Espelho versionado: retrato atual = vigente_ate IS NULL; retrato na data D = vigente_desde <= D AND "
                            "(vigente_ate IS NULL OR vigente_ate > D).")
        if tabela in _retencao():
            saida["retencao"] = _retencao()[tabela]
    registrar("descrever_tabela", {"tabela": tabela}, inicio, True)
    return saida


# --------------------------------------------------------------------------------------------------------------------------------------
# documentação

def _documentos():
    doc = CFG["documentacao"]
    achados = [RAIZ / f for f in doc["raiz_arquivos"] if (RAIZ / f).is_file()] + sorted(RAIZ.glob(doc["padrao_leiame"]))
    saida = []
    for p in achados:
        rel = p.relative_to(RAIZ).as_posix()
        if not any(fnmatch.fnmatch(rel, padrao) for padrao in doc["excluir"]) and rel not in saida:
            saida.append(rel)
    return saida


def ler_documentacao(nome=None):
    inicio = time.monotonic()
    docs = _documentos()
    if not nome:
        registrar("ler_documentacao", {"nome": None}, inicio, True)
        return {"documentos": docs, "nota": "Passe o caminho (ou parte dele, ex.: 'sicar', 'ibge/sidra') para ler um documento."}
    termo = nome.strip().lower().replace("\\", "/")
    exato = [d for d in docs if d.lower() == termo]
    candidatos = exato or [d for d in docs if termo in d.lower()]
    if len(candidatos) != 1:
        registrar("ler_documentacao", {"nome": nome}, inicio, False, "ambíguo ou inexistente")
        if not candidatos:
            raise ErroConsulta(f"nenhum documento com '{nome}'. Disponíveis: {', '.join(docs)}")
        raise ErroConsulta(f"'{nome}' combina com mais de um documento; escolha um: {', '.join(candidatos)}")
    texto = (RAIZ / candidatos[0]).read_text(encoding="utf-8")
    maximo = CFG["documentacao"]["caracteres_maximo"]
    registrar("ler_documentacao", {"nome": candidatos[0]}, inicio, True)
    return {"documento": candidatos[0], "texto": texto[:maximo] + ("\n… [cortado]" if len(texto) > maximo else "")}


# --------------------------------------------------------------------------------------------------------------------------------------
# consultar

def _relacoes(plano):
    """Tabelas lidas pela consulta, a partir do plano do EXPLAIN (views já aparecem expandidas nas tabelas de verdade)."""
    achadas = set()

    def andar(no):
        if isinstance(no, dict):
            if "Relation Name" in no and "Schema" in no:
                achadas.add(f"{no['Schema']}.{no['Relation Name']}")
            for v in no.values():
                andar(v)
        elif isinstance(no, list):
            for v in no:
                andar(v)
    andar(plano)
    return sorted(achadas)


def _expr_geometria(coluna, geography):
    c = sql.SQL("_q.{}").format(sql.Identifier(coluna))
    g = sql.SQL("{}::geometry").format(c) if geography else c
    geo = c if geography else sql.SQL("{}::geography").format(c)
    area = sql.SQL("round((ST_Area({geo}) / 10000)::numeric, 2)").format(geo=geo)
    comp = sql.SQL("round((ST_Length({geo}) / 1000)::numeric, 3)").format(geo=geo)
    if not geography:  # geography só para SRID geográfico conhecido; outros SRIDs ficam sem área
        area = sql.SQL("CASE WHEN ST_SRID({c}) IN (4674, 4326) THEN {a} END").format(c=c, a=area)
        comp = sql.SQL("CASE WHEN ST_SRID({c}) IN (4674, 4326) THEN {a} END").format(c=c, a=comp)
    return sql.SQL(
        "CASE WHEN {c} IS NULL THEN NULL ELSE jsonb_build_object("
        "'tipo', GeometryType({g}), 'srid', ST_SRID({g}), 'n_vertices', ST_NPoints({g}), "
        "'area_ha', CASE WHEN ST_Dimension({g}) = 2 THEN {area} END, "
        "'comprimento_km', CASE WHEN ST_Dimension({g}) = 1 THEN {comp} END, "
        "'centroide', ST_AsText(ST_Centroid({g}), 6)) END AS {nome}"
    ).format(c=c, g=g, area=area, comp=comp, nome=sql.Identifier(coluna))


def _avisos(texto, tabelas, versionadas):
    avisos = []
    sem_filtro = [t for t in tabelas if t in versionadas]
    if sem_filtro and not re.search(r"vigente_(ate|desde)", texto, re.I) and not any(t.split(".")[1].startswith("v_") for t in tabelas):
        avisos.append(f"A consulta lê tabela(s) versionada(s) ({', '.join(sem_filtro)}) sem filtrar a versão: conta vigentes E fechadas. "
                      "Para o retrato atual use vigente_ate IS NULL.")
    if re.search(r"st_area\s*\(", texto, re.I) and not re.search(r"geography|st_transform", texto, re.I):
        avisos.append("ST_Area em EPSG:4674 dá graus², não m². Use ST_Area(geom::geography) / 10000 para hectares.")
    return avisos


def consultar(consulta, limite=None):
    """Roda um SELECT somente leitura e devolve colunas, linhas, proveniência e avisos."""
    inicio = time.monotonic()
    texto = (consulta or "").strip().rstrip(";").strip()
    limite = max(1, min(int(limite or LIM["linhas_padrao"]), LIM["linhas_maximo"]))
    args = {"sql": texto, "limite": limite}
    if not texto:
        raise ErroConsulta("consulta vazia")
    # o SQL vai com parâmetro (LIMIT %s): '%' do usuário (LIKE 'a%') precisa virar '%%' para o psycopg
    corpo = sql.SQL(texto.replace("%", "%%"))
    try:
        with conectar() as conn, conn.cursor() as cur:
            _abrir(cur)
            cur.execute("SELECT oid, typname FROM pg_type WHERE typname IN ('geometry', 'geography')")
            tipos_geo = {oid: nome for oid, nome in cur.fetchall()}
            # 1) forma das colunas (LIMIT 0 não lê dado)
            cur.execute(sql.SQL("SELECT * FROM ({}) AS _q LIMIT %s").format(corpo), (0,))
            nomes = [d.name for d in cur.description]
            repetidas = sorted({n for n in nomes if nomes.count(n) > 1})
            if repetidas:
                raise ErroConsulta(f"colunas com o mesmo nome no resultado ({', '.join(repetidas)}): dê apelidos com AS")
            selecao = sql.SQL(", ").join(
                _expr_geometria(d.name, tipos_geo[d.type_code] == "geography") if d.type_code in tipos_geo
                else sql.SQL("_q.{}").format(sql.Identifier(d.name)) for d in cur.description)
            final = sql.SQL("SELECT {sel} FROM ({corpo}) AS _q LIMIT %s").format(sel=selecao, corpo=corpo)
            # 2) custo estimado e tabelas lidas
            cur.execute(sql.SQL("EXPLAIN (FORMAT JSON, VERBOSE) ") + final, (limite + 1,))
            plano = cur.fetchone()[0]
            custo = plano[0]["Plan"]["Total Cost"]
            tabelas = _relacoes(plano)
            if custo > LIM["custo_maximo"]:
                raise ErroConsulta(
                    f"consulta recusada: custo estimado {custo:,.0f} passa do limite {LIM['custo_maximo']:,.0f}. "
                    "Filtre antes por id_estado/id_municipio/id_bioma, use ST_Intersects (índice espacial) antes de ST_Intersection, "
                    "agregue no banco, ou divida em partes (por UF).")
            # 3) execução
            cur.execute(final, (limite + 1,))
            linhas = cur.fetchmany(limite + 1)
            mais = len(linhas) > limite
            linhas = [[_valor(v) for v in l] for l in linhas[:limite]]
            # proveniência das tabelas lidas
            cur.execute("""SELECT t AS tabela, d.nome AS dataset, f.nome AS fonte,
                                  (SELECT max(coletado_em) FROM catalogo.coletas c WHERE c.dataset = t) AS ultima_coleta,
                                  EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = to_regclass(t) AND a.attname = 'vigente_ate') AS versionada
                           FROM unnest(%s::text[]) AS t
                           LEFT JOIN catalogo.datasets d ON d.schema_tabela = t LEFT JOIN dim.fontes f USING (id_fonte)""", (tabelas,))
            prov = [dict(zip([d.name for d in cur.description], r)) for r in cur.fetchall()]
            conn.rollback()
    except ErroConsulta as e:
        registrar("consultar", args, inicio, False, str(e))
        raise
    except psycopg.errors.QueryCanceled as e:
        msg = (f"passou de {LIM['tempo_maximo_s']} s e foi cancelada. Filtre por UF/município/bioma, use o índice espacial "
               "(ST_Intersects, &&) ou agregue no banco.")
        registrar("consultar", args, inicio, False, msg)
        raise ErroConsulta(msg) from e
    except psycopg.errors.InsufficientPrivilege as e:
        msg = (f"sem permissão ({e.diag.message_primary}). A consulta usa coluna oculta (dado pessoal) ou tabela fora dos schemas liberados: "
               "descrever_tabela mostra as colunas disponíveis. Com coluna oculta, liste as colunas (SELECT * não funciona nessa tabela).")
        registrar("consultar", args, inicio, False, msg)
        raise ErroConsulta(msg) from e
    except psycopg.errors.ReadOnlySqlTransaction as e:
        registrar("consultar", args, inicio, False, "escrita")
        raise ErroConsulta("este acesso é somente leitura: só SELECT/WITH.") from e
    except psycopg.Error as e:
        msg = f"erro do PostgreSQL: {e.diag.message_primary or e}" + (f" (dica: {e.diag.message_hint})" if e.diag.message_hint else "")
        registrar("consultar", args, inicio, False, msg)
        raise ErroConsulta(msg) from e
    versionadas = {p["tabela"] for p in prov if p["versionada"]}
    saida = {
        "colunas": nomes, "linhas": linhas, "n_linhas": len(linhas), "ha_mais_linhas": mais,
        "custo_estimado": round(custo), "tempo_ms": round((time.monotonic() - inicio) * 1000),
        "proveniencia": [{k: _valor(v) for k, v in p.items() if v is not None and k != "versionada"} for p in prov],
        "avisos": _avisos(texto, tabelas, versionadas) + ([f"Resultado cortado em {limite} linhas: agregue ou filtre."] if mais else []),
        "sql": texto,
    }
    registrar("consultar", args, inicio, True, extra={"n_linhas": len(linhas), "custo": round(custo), "tabelas": tabelas})
    return saida
