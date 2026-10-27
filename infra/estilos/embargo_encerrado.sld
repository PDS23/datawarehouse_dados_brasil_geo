<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>embargo_encerrado</Name>
    <UserStyle>
      <Name>embargo_encerrado</Name>
      <Title>Areas desembargadas, embargo encerrado (visivel a partir de 1:2.000.000)</Title>
      <FeatureTypeStyle>
        <Rule>
          <Name>embargo_encerrado</Name>
          <Title>Area desembargada</Title>
          <!-- So desenha em escala maior que 1:2.000.000: sem isso o WMS tentaria desenhar a camada inteira e estouraria o tempo maximo. -->
          <MaxScaleDenominator>2000000</MaxScaleDenominator>
          <PolygonSymbolizer>
            <Fill>
              <CssParameter name="fill">#969696</CssParameter>
              <CssParameter name="fill-opacity">0.35</CssParameter>
            </Fill>
            <Stroke>
              <CssParameter name="stroke">#525252</CssParameter>
              <CssParameter name="stroke-width">0.5</CssParameter>
            </Stroke>
          </PolygonSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
