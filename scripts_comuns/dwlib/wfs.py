"""Cliente mínimo de WFS 1.1.0 (GML 3.1.1) sem GDAL: baixa a camada e converte cada feição em
(propriedades, geometria em EWKT) para o PostGIS ler direto (COPY aceita EWKT).

Por que não o GDAL: o leitor GML do GDAL leva ~2 min para 545 polígonos (a leitura é quadrática); este
parser faz o mesmo em milissegundos. Só entende Polygon e MultiSurface/MultiPolygon (o que o INCRA devolve)
e para com erro em qualquer outro tipo, em vez de gravar errado.

WFS 1.1.0 com EPSG:4326 devolve as coordenadas na ordem lat lon; aqui elas são trocadas para lon lat.
"""
import io
import re
import time
import xml.etree.ElementTree as ET

import requests

GML = "{http://www.opengis.net/gml}"
OWS = "{http://www.opengis.net/ows}"


class ErroWFS(Exception):
    """O servidor respondeu 200, mas com um relatório de exceção OGC (ou sem feições)."""


def baixar(url, tema, tentativas=3, espera=5, timeout=600):
    """GetFeature de uma camada inteira (bytes do GML). Repete em erro de rede; ErroWFS se o servidor devolver exceção."""
    params = {"tema": tema, "service": "WFS", "version": "1.1.0", "request": "GetFeature",
              "typename": tema, "srsName": "EPSG:4326"}
    ultimo = None
    for n in range(1, tentativas + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout,
                             headers={"User-Agent": "data-warehouse-gis/1.0 (coleta automatizada de dados abertos)"})
            r.raise_for_status()
            if b"ExceptionReport" in r.content[:2000]:
                msg = re.search(rb"<ows:ExceptionText>([^<]*)", r.content)
                raise ErroWFS(msg.group(1).decode("utf-8", "replace") if msg else "ExceptionReport sem texto")
            return r.content
        except ErroWFS as e:
            ultimo = e                       # erro de aplicação do servidor: repetir ajuda pouco, mas tenta
        except requests.RequestException as e:
            ultimo = e
        if n < tentativas:
            time.sleep(espera * n)
    raise ultimo


def _pares(poslist):
    v = [float(x) for x in poslist.split()]
    if len(v) % 2:
        raise ValueError("posList com número ímpar de valores")
    return [(v[i + 1], v[i]) for i in range(0, len(v), 2)]      # (lon, lat) a partir de (lat, lon)


def _poligono(el):
    """<gml:Polygon> -> lista de anéis, cada um uma lista de (lon, lat); o 1º é o exterior."""
    aneis = []
    ext = el.find(f"{GML}exterior/{GML}LinearRing/{GML}posList")
    if ext is None:
        raise ValueError("Polygon sem exterior/posList")
    aneis.append(_pares(ext.text))
    for i in el.findall(f"{GML}interior/{GML}LinearRing/{GML}posList"):
        aneis.append(_pares(i.text))
    return aneis


def _ewkt(poligonos, srid):
    def anel(a):
        return "(" + ",".join(f"{x:.7f} {y:.7f}" for x, y in a) + ")"
    return f"SRID={srid};MULTIPOLYGON(" + ",".join("(" + ",".join(anel(a) for a in p) + ")" for p in poligonos) + ")"


def geometria(el, srid):
    """Elemento de geometria GML 3.1.1 -> EWKT MULTIPOLYGON com o SRID dado (sem transformar coordenadas)."""
    tag = el.tag.replace(GML, "")
    if tag == "Polygon":
        polis = [_poligono(el)]
    elif tag in ("MultiSurface", "MultiPolygon"):
        polis = [_poligono(p) for p in el.iter(f"{GML}Polygon")]
        if not polis:
            raise ValueError(f"{tag} sem Polygon")
    else:
        raise ValueError(f"tipo de geometria não tratado: {tag}")
    return _ewkt(polis, srid)


def ewkt_de_geojson(geom, srid):
    """Geometria GeoJSON (Polygon/MultiPolygon, lon/lat) -> EWKT MULTIPOLYGON com o SRID dado (sem transformar)."""
    if geom is None:
        return None
    t, c = geom["type"], geom["coordinates"]
    if t == "Polygon":
        c = [c]
    elif t != "MultiPolygon":
        raise ValueError(f"GeoJSON: tipo não tratado ({t})")
    return _ewkt([[[(x, y) for x, y, *_ in anel] for anel in poli] for poli in c], srid)


def ewkt_de_wkb(wkb, srid):
    """WKB 2D (Polygon ou MultiPolygon, como o shapefile entrega via pyogrio) -> EWKT MULTIPOLYGON. Sem GDAL/shapely."""
    import struct
    pos = 0

    def u32():
        nonlocal pos
        v = struct.unpack_from(e + "I", wkb, pos)[0]
        pos += 4
        return v

    def poligono():
        nonlocal pos, e
        e = "<" if wkb[pos] == 1 else ">"
        pos += 1
        if u32() != 3:
            raise ValueError("WKB: esperado Polygon 2D")
        aneis = []
        for _ in range(u32()):
            n = u32()
            aneis.append(list(struct.iter_unpack(e + "dd", wkb[pos:pos + 16 * n])))
            pos += 16 * n
        return aneis

    e = "<" if wkb[0] == 1 else ">"
    tipo = struct.unpack_from(e + "I", wkb, 1)[0]
    if tipo == 3:
        return _ewkt([poligono()], srid)
    if tipo == 6:
        pos = 5
        return _ewkt([poligono() for _ in range(u32())], srid)
    raise ValueError(f"WKB: tipo de geometria não tratado ({tipo})")


def feicoes(gml_bytes, srid):
    """Itera (propriedades:dict[str,str|None], ewkt|None) de um GetFeature GML 3.1.1 do MapServer."""
    for _evento, el in ET.iterparse(io.BytesIO(gml_bytes), events=("end",)):
        if el.tag != f"{GML}featureMember":
            continue
        feicao = next(iter(el))
        props, ewkt = {}, None
        for filho in feicao:
            nome = filho.tag.rsplit("}", 1)[-1]
            if nome == "boundedBy":
                continue
            if nome == "msGeometry":
                g = next(iter(filho), None)
                ewkt = geometria(g, srid) if g is not None else None
            else:
                props[nome] = (filho.text or "").strip() or None
        yield props, ewkt
        el.clear()
