<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>mapa_tematico_ibge</Name>
    <UserStyle>
      <Name>mapa_tematico_ibge</Name>
      <Title>IBGE - mapas tematicos do BDiA (visivel a partir de 1:1.000.000)</Title>
      <FeatureTypeStyle>
        <Rule>
          <Name>feicao</Name>
          <Title>Feicao do mapa tematico</Title>
          <!-- Mais de 100 mil poligonos por camada: so desenha em escala maior que 1:1.000.000. -->
          <MaxScaleDenominator>1000000</MaxScaleDenominator>
          <PolygonSymbolizer>
            <Fill>
              <CssParameter name="fill">#c9b28a</CssParameter>
              <CssParameter name="fill-opacity">0.30</CssParameter>
            </Fill>
            <Stroke>
              <CssParameter name="stroke">#7a5c2e</CssParameter>
              <CssParameter name="stroke-width">0.3</CssParameter>
            </Stroke>
          </PolygonSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
