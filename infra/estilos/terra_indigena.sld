<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>terra_indigena</Name>
    <UserStyle>
      <Name>terra_indigena</Name>
      <Title>FUNAI - Terras indigenas</Title>
      <FeatureTypeStyle>
        <Rule>
          <Name>terra_indigena</Name>
          <Title>Terra indigena</Title>
          <PolygonSymbolizer>
            <Fill>
              <CssParameter name="fill">#e08a1e</CssParameter>
              <CssParameter name="fill-opacity">0.35</CssParameter>
            </Fill>
            <Stroke>
              <CssParameter name="stroke">#8a4b00</CssParameter>
              <CssParameter name="stroke-width">0.8</CssParameter>
            </Stroke>
          </PolygonSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
