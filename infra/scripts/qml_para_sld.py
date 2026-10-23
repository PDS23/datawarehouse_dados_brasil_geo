"""
Converte um estilo de raster do QGIS (.qml) em SLD, o formato do GeoServer.

Suporta os dois tipos de simbologia usados no projeto:
  - paletted (classes exatas, ex.: MapBiomas)      -> ColorMap type="values"
  - singlebandpseudocolor DISCRETE (faixas)         -> ColorMap type="intervals"
    (cada item do QML e o limite superior da faixa, igual ao SLD)

Uso:
    python qml_para_sld.py <entrada.qml> <saida.sld> --nome <id> --titulo "<texto>"
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

LIMITE_INT16 = 32767
VALOR_NODATA = -9999


def ler_qml(caminho):
    raiz = ET.parse(caminho).getroot()

    paleta = raiz.findall(".//colorPalette/paletteEntry")
    if paleta:
        entradas = [(float(e.get("value")), e.get("color"), e.get("label") or "") for e in paleta]
        return "values", sorted(entradas)

    itens = raiz.findall(".//colorrampshader/item")
    if itens:
        entradas = []
        for e in itens:
            valor = e.get("value")
            quantidade = LIMITE_INT16 if valor == "inf" else float(valor)
            entradas.append((quantidade, e.get("color"), e.get("label") or ""))
        return "intervals", sorted(entradas)

    sys.exit(f"Nenhuma paleta reconhecida em {caminho}")


def formatar(numero):
    return str(int(numero)) if float(numero).is_integer() else str(numero)


def montar_sld(tipo, entradas, nome, titulo):
    linhas = []
    if tipo == "intervals":
        # tudo abaixo de 0 (inclui o NoData -9999) fica transparente
        linhas.append('              <ColorMapEntry color="#000000" quantity="-1" opacity="0"/>')
    for quantidade, cor, rotulo in entradas:
        linhas.append(
            f"              <ColorMapEntry color={quoteattr(cor)} "
            f'quantity="{formatar(quantidade)}" label={quoteattr(rotulo)}/>'
        )
    corpo = "\n".join(linhas)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>{escape(nome)}</Name>
    <UserStyle>
      <Name>{escape(nome)}</Name>
      <Title>{escape(titulo)}</Title>
      <FeatureTypeStyle>
        <Rule>
          <RasterSymbolizer>
            <Opacity>1.0</Opacity>
            <ColorMap type="{tipo}">
{corpo}
            </ColorMap>
          </RasterSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("entrada", type=Path)
    parser.add_argument("saida", type=Path)
    parser.add_argument("--nome", required=True)
    parser.add_argument("--titulo", required=True)
    args = parser.parse_args()

    tipo, entradas = ler_qml(args.entrada)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(montar_sld(tipo, entradas, args.nome, args.titulo), encoding="utf-8")
    print(f"{args.saida.name}: {len(entradas)} entradas ({tipo})")


if __name__ == "__main__":
    main()
