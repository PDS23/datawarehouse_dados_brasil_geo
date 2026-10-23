<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>declividade_pct</Name>
    <UserStyle>
      <Name>declividade_pct</Name>
      <Title>Declividade em % (x10) - classes EMBRAPA</Title>
      <FeatureTypeStyle>
        <Rule>
          <RasterSymbolizer>
            <Opacity>1.0</Opacity>
            <ColorMap type="intervals">
              <ColorMapEntry color="#000000" quantity="-1" opacity="0"/>
              <ColorMapEntry color="#1a9850" quantity="30" label="0 a 3% (Plano)"/>
              <ColorMapEntry color="#91cf60" quantity="80" label="3 a 8% (Suave ondulado)"/>
              <ColorMapEntry color="#d9ef8b" quantity="200" label="8 a 20% (Ondulado)"/>
              <ColorMapEntry color="#fee08b" quantity="450" label="20 a 45% (Forte ondulado)"/>
              <ColorMapEntry color="#fc8d59" quantity="750" label="45 a 75% (Montanhoso)"/>
              <ColorMapEntry color="#d73027" quantity="32767" label="acima de 75% (Escarpado)"/>
            </ColorMap>
          </RasterSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
