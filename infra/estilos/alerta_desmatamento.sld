<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>alerta_desmatamento</Name>
    <UserStyle>
      <Name>alerta_desmatamento</Name>
      <Title>Alertas de desmatamento (DETER, MapBiomas Alerta; visivel a partir de 1:500.000)</Title>
      <FeatureTypeStyle>
        <Rule>
          <Name>alerta_desmatamento</Name>
          <Title>Alerta de desmatamento</Title>
          <!-- So desenha em escala maior que 1:500.000: sem isso o WMS tentaria desenhar a camada inteira e estouraria o tempo maximo. -->
          <MaxScaleDenominator>500000</MaxScaleDenominator>
          <PolygonSymbolizer>
            <Fill>
              <CssParameter name="fill">#e6550d</CssParameter>
              <CssParameter name="fill-opacity">0.7</CssParameter>
            </Fill>
            <Stroke>
              <CssParameter name="stroke">#7f2704</CssParameter>
              <CssParameter name="stroke-width">0.4</CssParameter>
            </Stroke>
          </PolygonSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
