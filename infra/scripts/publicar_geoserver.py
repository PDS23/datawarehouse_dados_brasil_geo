"""
Publica no GeoServer (via REST API) tudo que o projeto serve: workspace,
estilos SLD, stores PostGIS, camadas vetoriais, rasters COG e limites de
servico (WFS/WMS/WCS). A configuracao do GeoServer vira codigo: um GeoServer
novo (migracao, outra maquina, outra pessoa) sobe identico rodando este script.

Idempotente: o que ja existe e mantido ou atualizado, nunca duplicado nem
apagado. Credenciais e endereco vem de infra/.env.

Uso (tudo, na ordem certa):
    "C:\\Program Files\\QGIS 3.44.11\\apps\\Python312\\python.exe" publicar_geoserver.py
Uma parte so:
    ... publicar_geoserver.py --apenas vetoriais
    ... publicar_geoserver.py --apenas estilos rasters
Partes: workspace, estilos, stores, vetoriais, rasters, limites.

Parte opcional (fora da execucao padrao e a UNICA que apaga): limpar_demo
remove os dados de demonstracao que a imagem do GeoServer traz (workspaces
cite, it.geosolutions, nurc, sf, tiger, topp, ne e os grupos spearfish,
tasmania, tiger-ny). Por padrao so SIMULA; apaga de verdade com --sim:
    ... publicar_geoserver.py --apenas limpar_demo          (simulacao)
    ... publicar_geoserver.py --apenas limpar_demo --sim    (apaga)
O workspace do projeto (dw) nunca esta na lista.
"""

import argparse
import base64
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

INFRA = Path(__file__).resolve().parent.parent
WORKSPACE = "dw"
NAMESPACE_URI = "http://dw.local"
JSON = "application/json"
SLD = "application/vnd.ogc.sld+xml"

# Extensao anunciada das camadas vetoriais (Brasil, SIRGAS 2000). Fixa de
# proposito: calcular a extensao no banco varre a tabela (ou a juncao da view,
# no caso do PRODES) e o GeoServer so precisa de um retangulo aproximado.
BBOX_BRASIL = {"minx": -73.99, "miny": -33.75, "maxx": -28.83, "maxy": 5.28}

# (nome no GeoServer, arquivo em infra/estilos/)
ESTILOS = [
    ("mapbiomas_uso_solo", "mapbiomas_uso_solo.sld"),
    ("declividade_graus", "declividade_graus.sld"),
    ("declividade_pct", "declividade_pct.sld"),
    ("prodes_desmatamento", "prodes_desmatamento.sld"),
    ("sicar_imoveis", "sicar_imoveis.sld"),
    ("terra_indigena", "terra_indigena.sld"),
    ("unidade_conservacao", "unidade_conservacao.sld"),
    ("floresta_publica", "floresta_publica.sld"),
    ("alerta_desmatamento", "alerta_desmatamento.sld"),
    ("embargo", "embargo.sld"),
    ("embargo_ponto", "embargo_ponto.sld"),
    ("embargo_encerrado", "embargo_encerrado.sld"),
]

# (nome do store, schema do PostgreSQL). Um store por schema.
STORES = [
    ("dw_dim", "dim"),
    ("dw_vetorial", "vetorial"),
]

# Padrao: do ponto de vista do container, o Postgres nativo do Windows e este
# nome. Na stack com PostGIS em Docker, GEOSERVER_DB_HOST=postgis no .env.
DB_HOST_PADRAO = "host.docker.internal"
DB_PORTA = "5432"
DB_NOME = "data_warehouse"

# Camadas vetoriais. "estilo" ausente = fica o estilo padrao do GeoServer.
# "nativo" so e necessario se o nome publicado diferir do nome da tabela.
VETORIAIS = [
    {"store": "dw_dim", "nome": "biomas", "titulo": "Biomas do Brasil (IBGE)"},
    {"store": "dw_dim", "nome": "estados", "titulo": "Unidades da Federação (IBGE)"},
    {"store": "dw_dim", "nome": "municipios", "titulo": "Municípios do Brasil (IBGE)"},
    {"store": "dw_vetorial", "nome": "sicar_imoveis",
     "titulo": "SICAR - Imóveis rurais (CAR)",
     "resumo": "Cerca de 8,5 milhões de imóveis rurais do CAR, coletados do WFS "
               "público do CAR, cancelados inclusive (ind_status = CA). Tem "
               "histórico por versão: use vigente_ate IS NULL para o estado atual. "
               "Desenha só em escala maior que 1:250.000; para consultas use "
               "filtro por atributo (cod_estado, id_municipio). ATENÇÃO: 2 imóveis "
               "(1 no MA, 1 em SE) vêm do CAR com coordenadas inválidas e estão sem "
               "geometria (geom NULL, geom_anomala = true; o texto original fica em "
               "geom_origem_texto). Fonte e data da coleta por UF: "
               "catalogo.v_ultima_coleta.",
     "estilo": "sicar_imoveis"},
    {"store": "dw_vetorial", "nome": "v_prodes_municipio",
     "titulo": "PRODES - Desmatamento por município",
     "resumo": "Polígonos de desmatamento do PRODES (INPE). Um polígono que "
               "cruza a divisa aparece uma vez por município. Filtre por "
               "id_municipio (código IBGE) para consultas leves.",
     "estilo": "prodes_desmatamento"},
    # Fontes novas (2026-10-27): sempre por VIEW (infra/postgres/views_geoserver.sql), so a versao vigente. As de embargo NAO trazem nome nem documento do
    # embargado: o titular se obtem com infra/scripts/consultar_embargo.py (quem tem acesso ao banco).
    {"store": "dw_vetorial", "nome": "v_funai_terras_indigenas", "titulo": "FUNAI - Terras indígenas",
     "resumo": "665 terras indígenas da FUNAI (WFS da FUNAI), versão vigente. fase_ti diz a fase do processo (declarada, homologada, regularizada...).",
     "estilo": "terra_indigena"},
    {"store": "dw_vetorial", "nome": "v_mma_unidades_conservacao", "titulo": "MMA - Unidades de conservação (CNUC)",
     "resumo": "3.406 unidades de conservação com polígono (CNUC, MMA), edição 2026_07, versão vigente. As 170 UCs que só têm ponto esquemático não estão nesta camada. "
               "esfera varia a capitalização (Federal/federal): use lower().",
     "estilo": "unidade_conservacao"},
    {"store": "dw_vetorial", "nome": "v_mma_areas_prioritarias", "titulo": "MMA - Áreas prioritárias para a conservação da biodiversidade",
     "resumo": "2.081 áreas prioritárias do MMA (2ª atualização, 2022) em 7 camadas de origem (camada_origem): Amazônia, Caatinga, Cerrado e Pantanal, Mata Atlântica, Pampa, Zona Costeira e Marinha e Áreas Híbridas. "
               "A capitalização de prioridade_acao varia: use lower(). Pode haver sobreposição entre camadas.",
     "estilo": "unidade_conservacao"},
    {"store": "dw_vetorial", "nome": "v_sfb_florestas_publicas", "titulo": "SFB - Florestas públicas (CNFP)",
     "resumo": "Cadastro Nacional de Florestas Públicas (SFB), edição 2025: assentamentos, UCs, terras indígenas, glebas e áreas militares. Há sobreposição entre registros "
               "(sobreposic = SIM): não some área sem filtrar. Desenha só em escala maior que 1:5.000.000.",
     "estilo": "floresta_publica"},
    {"store": "dw_vetorial", "nome": "v_deter_alertas", "titulo": "DETER (INPE) - Alertas de desmatamento, Amazônia e Cerrado",
     "resumo": "Cerca de 600 mil alertas do DETER (INPE), versão vigente. É alerta, não o dado oficial de desmatamento (PRODES). Desenha só em escala maior que 1:500.000; "
               "para consultas filtre por uf, id_municipio ou publish_month (o WFS corta em 100.000 feições, em silêncio).",
     "estilo": "alerta_desmatamento"},
    {"store": "dw_vetorial", "nome": "v_mapbiomas_alerta", "titulo": "MapBiomas Alerta - Alertas validados de desmatamento",
     "resumo": "Cerca de 540 mil alertas validados do MapBiomas Alerta, versão vigente. Desenha só em escala maior que 1:500.000; filtre por estado ou ano antes de pedir feições "
               "(o WFS corta em 100.000, em silêncio).",
     "estilo": "alerta_desmatamento"},
    {"store": "dw_vetorial", "nome": "v_ibama_embargos_poligonos", "titulo": "IBAMA - Termos de embargo (com polígono)",
     "resumo": "Termos de embargo do IBAMA que têm polígono (~60 mil), versão vigente, INCLUSIVE os já desembargados (veja sit_desembargo e sit_cancelado). Sem nome nem documento do "
               "embargado: use o identificador chave_tad (ou num_auto_infracao, num_processo) com infra/scripts/consultar_embargo.py para saber o titular. Desenha só em escala maior que 1:2.000.000.",
     "estilo": "embargo"},
    {"store": "dw_vetorial", "nome": "v_ibama_embargos_pontos", "titulo": "IBAMA - Termos de embargo (só ponto)",
     "resumo": "Termos de embargo do IBAMA SEM polígono, só com o ponto (latitude/longitude do termo): o ponto indica o lugar, não a área embargada. Sem nome nem documento do embargado: "
               "use chave_tad com infra/scripts/consultar_embargo.py. Há ainda cerca de 15 mil termos sem geometria nenhuma, que só aparecem na busca por documento.",
     "estilo": "embargo_ponto"},
    {"store": "dw_vetorial", "nome": "v_icmbio_areas_embargadas", "titulo": "ICMBio - Áreas embargadas",
     "resumo": "Áreas embargadas pelo ICMBio (~14,5 mil polígonos), versão vigente. Um embargo (numero_emb) tem vários polígonos. Sem nome nem documento do autuado: use numero_emb "
               "(ou numero_ai, processo) com infra/scripts/consultar_embargo.py. area_texto é texto livre da fonte, não a área do polígono.",
     "estilo": "embargo"},
    {"store": "dw_vetorial", "nome": "v_sema_mt_areas_embargadas", "titulo": "SEMA-MT - Áreas embargadas (Mato Grosso)",
     "resumo": "Áreas embargadas pela SEMA-MT (Mato Grosso), embargo vigente, versão vigente. Sem nome nem documento: use t_embargo com infra/scripts/consultar_embargo.py.",
     "estilo": "embargo"},
    {"store": "dw_vetorial", "nome": "v_sema_mt_areas_desembargadas", "titulo": "SEMA-MT - Áreas desembargadas (Mato Grosso, embargo encerrado)",
     "resumo": "Áreas cujo embargo pela SEMA-MT foi ENCERRADO: não contam como embargo vigente. Sem nome nem documento: use t_embargo com infra/scripts/consultar_embargo.py.",
     "estilo": "embargo_encerrado"},
]

# Campos que o WCS exige e que a tela do GeoServer preenche sozinha, mas uma
# cobertura criada por REST so com o nome nao tem.
METADADOS_WCS = {
    "enabled": True,
    "srs": "EPSG:4674",
    "nativeFormat": "GeoTIFF",
    "defaultInterpolationMethod": "nearest neighbor",
    "interpolationMethods": {"string": ["nearest neighbor", "bilinear", "bicubic"]},
    "supportedFormats": {"string": ["GEOTIFF", "GIF", "PNG", "JPEG", "TIFF"]},
    "requestSRS": {"string": ["EPSG:4674"]},
    "responseSRS": {"string": ["EPSG:4674"]},
}

# (nome da camada/store, caminho DENTRO do container, estilo, titulo)
RASTERS = [
    ("mapbiomas_1985", "/rasters/mapbiomas/brazil_coverage-col11_1985_cog.tif",
     "mapbiomas_uso_solo", "MapBiomas Uso do Solo 1985 (Colecao 11)"),
    ("mapbiomas_2008", "/rasters/mapbiomas/brazil_coverage-col11_2008_cog.tif",
     "mapbiomas_uso_solo", "MapBiomas Uso do Solo 2008 (Colecao 11)"),
    ("mapbiomas_2015", "/rasters/mapbiomas/brazil_coverage-col11_2015_cog.tif",
     "mapbiomas_uso_solo", "MapBiomas Uso do Solo 2015 (Colecao 11)"),
    ("mapbiomas_2025", "/rasters/mapbiomas/brazil_coverage-col11_2025_cog.tif",
     "mapbiomas_uso_solo", "MapBiomas Uso do Solo 2025 (Colecao 11)"),
    ("topodata_declividade_graus_rs_sc",
     "/rasters/topodata/rs_sc/rs_sc_declividade_graus_int16cog.tif",
     "declividade_graus", "TOPODATA Declividade em graus (x100) RS+SC"),
    ("topodata_declividade_pct_rs_sc",
     "/rasters/topodata/rs_sc/rs_sc_declividade_pct_int16cog.tif",
     "declividade_pct", "TOPODATA Declividade em % (x10) RS+SC"),
]

# Guardas pra nao sobrecarregar o servidor (motivos em LEIAME_infra.md).
# (servico, corpo do PUT em /rest/services/<servico>/settings)
LIMITES = [
    ("wfs", {"wfs": {"maxFeatures": 100000}}),
    ("wms", {"wms": {"maxRequestMemory": 65536, "maxRenderingTime": 60,
                     "maxRenderingErrors": 1000}}),
    ("wcs", {"wcs": {"maxInputMemory": 524288, "maxOutputMemory": 262144,
                     "overviewPolicy": "NEAREST"}}),
]

PARTES = ["workspace", "estilos", "stores", "vetoriais", "rasters", "limites"]
PARTES_OPCIONAIS = ["limpar_demo"]

# Dados de demonstracao que a imagem docker.osgeo.org/geoserver traz. Lista
# FIXA de proposito: so o que esta aqui pode ser apagado (e o workspace do
# projeto, WORKSPACE, nunca entra nela).
DEMO_WORKSPACES = ["cite", "it.geosolutions", "nurc", "sde", "sf", "tiger", "topp", "ne"]
DEMO_GRUPOS = ["spearfish", "tasmania", "tiger-ny"]


def ler_env():
    config = {}
    for linha in (INFRA / ".env").read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            config[chave.strip()] = valor.strip()
    return config


def resumo_erro(corpo):
    texto = corpo.decode(errors="replace")
    texto = re.sub(r"(?s)<style.*?</style>", " ", texto)
    texto = re.sub(r"<[^>]+>", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()[:600]


class GeoServer:
    def __init__(self, env):
        host = env.get("GEOSERVER_BIND_IP", "127.0.0.1")
        porta = env.get("GEOSERVER_PORT", "8080")
        usuario = env.get("GEOSERVER_ADMIN_USER", "admin")
        senha = env["GEOSERVER_ADMIN_PASSWORD"]
        self.rest = f"http://{host}:{porta}/geoserver/rest"
        self.auth = "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()
        self.falhas = 0
        self.apagar = False  # so a parte limpar_demo com --sim liga isto

    def pedir(self, metodo, caminho, corpo=None, tipo=None):
        cabecalhos = {"Authorization": self.auth}
        if tipo:
            cabecalhos["Content-Type"] = tipo
        req = urllib.request.Request(
            f"{self.rest}/{caminho}", data=corpo, method=metodo, headers=cabecalhos)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as erro:
            return erro.code, erro.read()

    def pedir_json(self, metodo, caminho, objeto):
        return self.pedir(metodo, caminho, json.dumps(objeto).encode(), JSON)

    def existe(self, caminho):
        status, _ = self.pedir("GET", caminho)
        return status == 200

    def falhou(self, nome, o_que, status, corpo):
        self.falhas += 1
        print(f"  {nome}: ERRO ao {o_que} HTTP {status} {resumo_erro(corpo)}")


def garantir_workspace(gs, env):
    if not gs.existe(f"workspaces/{WORKSPACE}.json"):
        status, corpo = gs.pedir_json("POST", "workspaces", {"workspace": {"name": WORKSPACE}})
        if status != 201:
            return gs.falhou(WORKSPACE, "criar workspace", status, corpo)
        print(f"  workspace {WORKSPACE}: criado")
    else:
        print(f"  workspace {WORKSPACE}: ja existia")
    # Criar o workspace cria um namespace "http://<nome>"; o projeto usa outro URI.
    status, corpo = gs.pedir("GET", f"namespaces/{WORKSPACE}.json")
    atual = json.loads(corpo)["namespace"]["uri"] if status == 200 else None
    if atual != NAMESPACE_URI:
        status, corpo = gs.pedir_json(
            "PUT", f"namespaces/{WORKSPACE}",
            {"namespace": {"prefix": WORKSPACE, "uri": NAMESPACE_URI}})
        if status != 200:
            return gs.falhou(WORKSPACE, "ajustar namespace", status, corpo)
        print(f"  namespace {WORKSPACE}: URI ajustado para {NAMESPACE_URI}")


def publicar_estilos(gs, env):
    for nome, arquivo in ESTILOS:
        sld = (INFRA / "estilos" / arquivo).read_bytes()
        if gs.existe(f"workspaces/{WORKSPACE}/styles/{nome}.json"):
            status, corpo = gs.pedir("PUT", f"workspaces/{WORKSPACE}/styles/{nome}", sld, SLD)
            acao = "atualizado"
        else:
            status, corpo = gs.pedir(
                "POST", f"workspaces/{WORKSPACE}/styles?name={nome}", sld, SLD)
            acao = "criado"
        if status in (200, 201):
            print(f"  {nome}: {acao}")
        else:
            gs.falhou(nome, "enviar estilo", status, corpo)


def parametros_postgis(env, schema):
    parametros = {
        "dbtype": "postgis", "host": env.get("GEOSERVER_DB_HOST", DB_HOST_PADRAO),
        "port": DB_PORTA, "database": DB_NOME,
        "schema": schema, "user": env.get("GEOSERVER_DB_USER", "geoserver"),
        "passwd": env["GEOSERVER_DB_PASSWORD"], "namespace": NAMESPACE_URI,
        # Sem "Expose primary keys" o WFS nao deixa filtrar/ler a coluna de chave.
        "Expose primary keys": "true",
        "Loose bbox": "true", "Estimated extends": "true",
        "validate connections": "true", "Support on the fly geometry simplification": "true",
        "min connections": "1", "max connections": "10", "fetch size": "1000",
        "Connection timeout": "20", "SSL mode": "DISABLE",
    }
    return {"entry": [{"@key": k, "$": v} for k, v in parametros.items()]}


def publicar_stores(gs, env):
    for nome, schema in STORES:
        if gs.existe(f"workspaces/{WORKSPACE}/datastores/{nome}.json"):
            print(f"  {nome}: ja existia (mantido, senha nao e reenviada)")
            continue
        if "GEOSERVER_DB_PASSWORD" not in env:
            gs.falhas += 1
            print(f"  {nome}: ERRO nao existe e falta GEOSERVER_DB_PASSWORD no .env "
                  f"(senha do papel de banco 'geoserver')")
            continue
        store = {"dataStore": {
            "name": nome, "type": "PostGIS", "enabled": True,
            "workspace": {"name": WORKSPACE},
            "connectionParameters": parametros_postgis(env, schema)}}
        status, corpo = gs.pedir_json("POST", f"workspaces/{WORKSPACE}/datastores", store)
        if status == 201:
            print(f"  {nome}: criado (schema {schema})")
        else:
            gs.falhou(nome, "criar store", status, corpo)


def publicar_vetoriais(gs, env):
    for item in VETORIAIS:
        nome, store = item["nome"], item["store"]
        base = f"workspaces/{WORKSPACE}/datastores/{store}/featuretypes"
        existia = gs.existe(f"layers/{WORKSPACE}:{nome}.json")

        if not existia:
            tipo = {"featureType": {
                "name": nome, "nativeName": item.get("nativo", nome), "enabled": True,
                "srs": "EPSG:4674", "projectionPolicy": "FORCE_DECLARED",
                "nativeBoundingBox": {**BBOX_BRASIL, "crs": "EPSG:4674"},
                "latLonBoundingBox": {**BBOX_BRASIL, "crs": "EPSG:4326"}}}
            status, corpo = gs.pedir_json("POST", base, tipo)
            if status != 201:
                gs.falhou(nome, "publicar camada", status, corpo)
                continue

        # Roda sempre: titulo/resumo e estilo ficam sob controle do script.
        descricao = {"featureType": {"title": item["titulo"]}}
        if "resumo" in item:
            descricao["featureType"]["abstract"] = item["resumo"]
        status, corpo = gs.pedir_json("PUT", f"{base}/{nome}", descricao)
        if status != 200:
            gs.falhou(nome, "atualizar titulo", status, corpo)
            continue

        if "estilo" in item:
            definicao = {"layer": {"defaultStyle": {"name": item["estilo"], "workspace": WORKSPACE}}}
            status, corpo = gs.pedir_json("PUT", f"layers/{WORKSPACE}:{nome}", definicao)
            if status != 200:
                gs.falhou(nome, "aplicar estilo", status, corpo)
                continue

        estilo = f" (estilo {item['estilo']})" if "estilo" in item else ""
        print(f"  {nome}: {'ja existia, atualizado' if existia else 'publicado'}{estilo}")


def nomes_configurados(corpo):
    dados = json.loads(corpo).get("coverages")
    if not isinstance(dados, dict):
        return []
    itens = dados.get("coverage", [])
    if isinstance(itens, dict):
        itens = [itens]
    return [item["name"] for item in itens]


def publicar_rasters(gs, env):
    for nome, caminho, estilo, titulo in RASTERS:
        base_store = f"workspaces/{WORKSPACE}/coveragestores"
        existia = gs.existe(f"layers/{WORKSPACE}:{nome}.json")

        if not existia:
            if not gs.existe(f"{base_store}/{nome}.json"):
                store = {"coverageStore": {
                    "name": nome, "type": "GeoTIFF", "enabled": True,
                    "workspace": {"name": WORKSPACE}, "url": f"file://{caminho}"}}
                status, corpo = gs.pedir_json("POST", base_store, store)
                if status not in (200, 201):
                    gs.falhou(nome, "criar store", status, corpo)
                    continue

            # O GeoServer nomeia a cobertura nativa de um GeoTIFF pelo nome do
            # arquivo sem extensao.
            nativo = Path(caminho).stem
            status, corpo = gs.pedir("GET", f"{base_store}/{nome}/coverages.json")
            configuradas = nomes_configurados(corpo) if status == 200 else []

            if nativo in configuradas:
                # ja publicada (ex.: pela tela) com o nome do arquivo: so renomeia
                status, corpo = gs.pedir_json(
                    "PUT", f"{base_store}/{nome}/coverages/{nativo}",
                    {"coverage": {"name": nome}})
                if status != 200:
                    gs.falhou(nome, "renomear cobertura existente", status, corpo)
                    continue
            else:
                status, corpo = gs.pedir_json(
                    "POST", f"{base_store}/{nome}/coverages",
                    {"coverage": {"name": nome, "nativeCoverageName": nativo, "enabled": True}})
                if status not in (200, 201):
                    gs.falhou(nome, "publicar cobertura", status, corpo)
                    continue

        # Roda sempre (tambem em camada ja existente): o WCS so funciona
        # quando formatos, interpolacao e SRS estao cadastrados, e uma
        # cobertura criada so com o nome nao os tem.
        status, corpo = gs.pedir_json(
            "PUT", f"{base_store}/{nome}/coverages/{nome}",
            {"coverage": {**METADADOS_WCS, "title": titulo}})
        if status != 200:
            gs.falhou(nome, "completar metadados WCS", status, corpo)
            continue

        status, corpo = gs.pedir_json(
            "PUT", f"layers/{WORKSPACE}:{nome}",
            {"layer": {"defaultStyle": {"name": estilo, "workspace": WORKSPACE}}})
        if status != 200:
            gs.falhou(nome, "aplicar estilo", status, corpo)
            continue

        print(f"  {nome}: {'ja existia, atualizado' if existia else 'publicado'} (estilo {estilo})")


def aplicar_limites(gs, env):
    for servico, corpo_put in LIMITES:
        status, corpo = gs.pedir_json("PUT", f"services/{servico}/settings", corpo_put)
        if status == 200:
            campos = ", ".join(f"{k}={v}" for k, v in next(iter(corpo_put.values())).items())
            print(f"  {servico}: {campos}")
        else:
            gs.falhou(servico, "aplicar limites", status, corpo)


def nomes_da_lista(corpo, raiz, item):
    """Nomes de uma listagem REST (vazia vem como string em vez de objeto)."""
    dados = json.loads(corpo).get(raiz)
    if not isinstance(dados, dict):
        return []
    return [x["name"] for x in dados.get(item, [])]


def limpar_demo(gs, env):
    """Remove os dados de demonstracao do GeoServer. Simula sem --sim."""
    assert WORKSPACE not in DEMO_WORKSPACES and WORKSPACE not in DEMO_GRUPOS
    modo = "apagando" if gs.apagar else "SIMULACAO, nada sera apagado (use --sim)"
    print(f"  {modo}")

    status, corpo = gs.pedir("GET", "layergroups.json")
    if status != 200:
        return gs.falhou("layergroups", "listar", status, corpo)
    grupos = [g for g in nomes_da_lista(corpo, "layerGroups", "layerGroup") if g in DEMO_GRUPOS]

    status, corpo = gs.pedir("GET", "workspaces.json")
    if status != 200:
        return gs.falhou("workspaces", "listar", status, corpo)
    existentes = nomes_da_lista(corpo, "workspaces", "workspace")
    alvos = [w for w in existentes if w in DEMO_WORKSPACES]
    mantidos = [w for w in existentes if w not in DEMO_WORKSPACES]
    print(f"  workspaces mantidos: {', '.join(mantidos) or '(nenhum)'}")

    # Grupos globais primeiro (referenciam camadas dos workspaces).
    for nome in grupos:
        if not gs.apagar:
            print(f"  grupo {nome}: removeria")
            continue
        status, corpo = gs.pedir("DELETE", f"layergroups/{nome}")
        if status == 200:
            print(f"  grupo {nome}: removido")
        else:
            gs.falhou(nome, "remover grupo", status, corpo)

    for nome in alvos:
        _, corpo_camadas = gs.pedir("GET", f"workspaces/{nome}/layers.json")
        camadas = len(nomes_da_lista(corpo_camadas, "layers", "layer"))
        if not gs.apagar:
            print(f"  workspace {nome}: removeria (com {camadas} camada(s) e tudo dentro)")
            continue
        # ".json" no caminho: sem ele, o ponto de nomes como it.geosolutions e
        # lido como extensao de arquivo e a API procura o workspace "it".
        status, corpo = gs.pedir("DELETE", f"workspaces/{nome}.json?recurse=true")
        if status == 200:
            print(f"  workspace {nome}: removido ({camadas} camada(s))")
        else:
            gs.falhou(nome, "remover workspace", status, corpo)

    if not grupos and not alvos:
        print("  nada de demonstracao encontrado")


EXECUTORES = {
    "workspace": garantir_workspace,
    "estilos": publicar_estilos,
    "stores": publicar_stores,
    "vetoriais": publicar_vetoriais,
    "rasters": publicar_rasters,
    "limites": aplicar_limites,
    "limpar_demo": limpar_demo,
}


def main():
    parser = argparse.ArgumentParser(description="Publica o catalogo do projeto no GeoServer.")
    parser.add_argument("--apenas", nargs="+", choices=PARTES + PARTES_OPCIONAIS, metavar="PARTE",
                        help=f"rodar so estas partes ({', '.join(PARTES + PARTES_OPCIONAIS)}); "
                             f"padrao: todas, menos as opcionais ({', '.join(PARTES_OPCIONAIS)})")
    parser.add_argument("--sim", action="store_true",
                        help="confirma a remocao de limpar_demo (sem isso, so simula)")
    parser.add_argument("--recriar", nargs="+", metavar="CAMADA",
                        help="antes de publicar, APAGA a camada vetorial (so a publicacao no GeoServer, nao a tabela) para ela ser "
                             "recriada com as colunas atuais da tabela; use depois de mudar a estrutura de uma tabela")
    args = parser.parse_args()
    partes = [p for p in PARTES + PARTES_OPCIONAIS
              if (args.apenas and p in args.apenas) or (not args.apenas and p in PARTES)]

    env = ler_env()
    gs = GeoServer(env)
    gs.apagar = args.sim
    status, _ = gs.pedir("GET", "about/version.json")
    if status != 200:
        sys.exit(f"Nao autenticou/alcancou o GeoServer em {gs.rest} (HTTP {status}).")

    for nome in args.recriar or []:
        item = next((i for i in VETORIAIS if i["nome"] == nome), None)
        if item is None:
            sys.exit(f"--recriar: '{nome}' nao esta em VETORIAIS ({', '.join(i['nome'] for i in VETORIAIS)})")
        print(f"== recriar {nome}: apagando a publicacao (a tabela nao e tocada) ==")
        gs.pedir("DELETE", f"layers/{WORKSPACE}:{nome}")
        status, corpo = gs.pedir("DELETE", f"workspaces/{WORKSPACE}/datastores/{item['store']}/featuretypes/{nome}?recurse=true")
        print(f"  {nome}: DELETE featuretype HTTP {status}")

    for parte in partes:
        print(f"== {parte} ==")
        EXECUTORES[parte](gs, env)

    print("Concluido." if not gs.falhas else f"Concluido com {gs.falhas} falha(s).")
    sys.exit(1 if gs.falhas else 0)


if __name__ == "__main__":
    main()
