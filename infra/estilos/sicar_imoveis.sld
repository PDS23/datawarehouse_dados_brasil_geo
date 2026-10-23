<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>sicar_imoveis</Name>
    <UserStyle>
      <Name>sicar_imoveis</Name>
      <Title>SICAR - Imoveis rurais (visivel a partir de 1:250.000)</Title>
      <FeatureTypeStyle>
        <Rule>
          <Name>imovel</Name>
          <Title>Imovel rural</Title>
          <!-- 8,3 milhoes de imoveis: so desenha em escala maior que
               1:250.000, senao o WMS estoura o tempo de renderizacao. -->
          <MaxScaleDenominator>250000</MaxScaleDenominator>
          <PolygonSymbolizer>
            <Fill>
              <CssParameter name="fill">#3182bd</CssParameter>
              <CssParameter name="fill-opacity">0.15</CssParameter>
            </Fill>
            <Stroke>
              <CssParameter name="stroke">#08519c</CssParameter>
              <CssParameter name="stroke-width">0.6</CssParameter>
            </Stroke>
          </PolygonSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
