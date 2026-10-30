<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>hidrografia_linha</Name>
    <UserStyle>
      <Name>hidrografia_linha</Name>
      <Title>ANA - Hidrografia, linhas (visivel a partir de 1:1000000)</Title>
      <FeatureTypeStyle>
        <Rule>
          <Name>hidrografia_linha</Name>
          <Title>ANA - Hidrografia, linhas (visivel a partir de 1:1000000)</Title>
          <!-- Camada grande: so desenha em escala maior que 1:1000000. -->
          <MaxScaleDenominator>1000000</MaxScaleDenominator>
          <LineSymbolizer>
            <Stroke>
              <CssParameter name="stroke">#2b7bba</CssParameter>
              <CssParameter name="stroke-width">0.8</CssParameter>
            </Stroke>
          </LineSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
