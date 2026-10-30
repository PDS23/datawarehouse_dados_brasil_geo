<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>bacia_hidrografica</Name>
    <UserStyle>
      <Name>bacia_hidrografica</Name>
      <Title>ANA - Bacias hidrograficas Otto (visivel a partir de 1:5000000)</Title>
      <FeatureTypeStyle>
        <Rule>
          <Name>bacia_hidrografica</Name>
          <Title>ANA - Bacias hidrograficas Otto (visivel a partir de 1:5000000)</Title>
          <!-- Camada grande: so desenha em escala maior que 1:5000000. -->
          <MaxScaleDenominator>5000000</MaxScaleDenominator>
          <PolygonSymbolizer>
            <Fill>
              <CssParameter name="fill">#a6cee3</CssParameter>
              <CssParameter name="fill-opacity">0.15</CssParameter>
            </Fill>
            <Stroke>
              <CssParameter name="stroke">#1f78b4</CssParameter>
              <CssParameter name="stroke-width">0.8</CssParameter>
            </Stroke>
          </PolygonSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
