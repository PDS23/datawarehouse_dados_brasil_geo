<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>declividade_graus</Name>
    <UserStyle>
      <Name>declividade_graus</Name>
      <Title>Declividade em graus (x100) - classes EMBRAPA</Title>
      <FeatureTypeStyle>
        <Rule>
          <RasterSymbolizer>
            <Opacity>1.0</Opacity>
            <ColorMap type="intervals">
              <ColorMapEntry color="#000000" quantity="-1" opacity="0"/>
              <ColorMapEntry color="#1a9850" quantity="172" label="0 a 1,72° (Plano, 0-3%)"/>
              <ColorMapEntry color="#91cf60" quantity="457" label="1,72 a 4,57° (Suave ondulado, 3-8%)"/>
              <ColorMapEntry color="#d9ef8b" quantity="1131" label="4,57 a 11,31° (Ondulado, 8-20%)"/>
              <ColorMapEntry color="#fee08b" quantity="2423" label="11,31 a 24,23° (Forte ondulado, 20-45%)"/>
              <ColorMapEntry color="#fc8d59" quantity="3687" label="24,23 a 36,87° (Montanhoso, 45-75%)"/>
              <ColorMapEntry color="#d73027" quantity="32767" label="acima de 36,87° (Escarpado, &gt;75%)"/>
            </ColorMap>
          </RasterSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
