<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>floresta_publica</Name>
    <UserStyle>
      <Name>floresta_publica</Name>
      <Title>SFB - Florestas publicas (CNFP)</Title>
      <FeatureTypeStyle>
        <Rule>
          <Name>floresta_publica</Name>
          <Title>Floresta publica</Title>
          <!-- So desenha em escala maior que 1:5.000.000: sem isso o WMS tentaria desenhar a camada inteira e estouraria o tempo maximo. -->
          <MaxScaleDenominator>5000000</MaxScaleDenominator>
          <PolygonSymbolizer>
            <Fill>
              <CssParameter name="fill">#1f9e9e</CssParameter>
              <CssParameter name="fill-opacity">0.3</CssParameter>
            </Fill>
            <Stroke>
              <CssParameter name="stroke">#0b5d5d</CssParameter>
              <CssParameter name="stroke-width">0.4</CssParameter>
            </Stroke>
          </PolygonSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
