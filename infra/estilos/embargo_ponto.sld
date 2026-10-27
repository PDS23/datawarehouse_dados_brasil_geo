<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>embargo_ponto</Name>
    <UserStyle>
      <Name>embargo_ponto</Name>
      <Title>Embargos so com ponto (visivel a partir de 1:2.000.000)</Title>
      <FeatureTypeStyle>
        <Rule>
          <Name>embargo_ponto</Name>
          <Title>Embargo (ponto)</Title>
          <!-- So desenha em escala maior que 1:2.000.000: sem isso o WMS tentaria desenhar a camada inteira e estouraria o tempo maximo. -->
          <MaxScaleDenominator>2000000</MaxScaleDenominator>
          <PointSymbolizer>
            <Graphic>
              <Mark>
                <WellKnownName>circle</WellKnownName>
                <Fill><CssParameter name="fill">#cb181d</CssParameter></Fill>
                <Stroke><CssParameter name="stroke">#ffffff</CssParameter><CssParameter name="stroke-width">0.5</CssParameter></Stroke>
              </Mark>
              <Size>6</Size>
            </Graphic>
          </PointSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
