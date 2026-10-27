<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>embargo</Name>
    <UserStyle>
      <Name>embargo</Name>
      <Title>Areas embargadas (visivel a partir de 1:2.000.000)</Title>
      <FeatureTypeStyle>
        <Rule>
          <Name>embargo</Name>
          <Title>Area embargada</Title>
          <!-- So desenha em escala maior que 1:2.000.000: sem isso o WMS tentaria desenhar a camada inteira e estouraria o tempo maximo. -->
          <MaxScaleDenominator>2000000</MaxScaleDenominator>
          <PolygonSymbolizer>
            <Fill>
              <CssParameter name="fill">#cb181d</CssParameter>
              <CssParameter name="fill-opacity">0.45</CssParameter>
            </Fill>
            <Stroke>
              <CssParameter name="stroke">#67000d</CssParameter>
              <CssParameter name="stroke-width">0.6</CssParameter>
            </Stroke>
          </PolygonSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
