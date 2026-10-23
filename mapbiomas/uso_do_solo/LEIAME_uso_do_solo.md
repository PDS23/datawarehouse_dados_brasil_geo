# mapbiomas/uso_do_solo — MapBiomas Coleção 11: cobertura e uso do solo (raster, Brasil inteiro, um arquivo por ano)

> **Documento restaurado em 2026-10-20** a partir do texto do notebook (escrito em 2026-10-01; era o LEIAME de todo o
> `mapbiomas/`, por isso cita também `pastagem_vigor`, que não está neste repositório). Estado em relação ao padrão de
> fontes (ARQUITETURA.md): a conversão para COG foi feita por comando solto (abaixo) e **ainda não virou script em
> `scripts/` nem há `config.yaml`**; MapBiomas é fonte **por edição** (coleção) e **por ano de mapa**: o ano fica no nome do
> arquivo e em `catalogo.datasets.ano_referencia`, não em pasta. Os COG de `processado/` são montados no GeoServer
> (`infra/docker-compose.stack.yml`) e citados em `catalogo.datasets` pelo caminho `mapbiomas/uso_do_solo/processado/...`:
> **não mover sem ajustar os dois**. `processado/` não está no git; está no Drive para a equipe.

## Organização

```
mapbiomas/uso_do_solo/
├── LEIAME_uso_do_solo.md          este arquivo
├── scripts/                       (vazio: a conversão para COG ainda é o comando documentado abaixo)
└── processado/                    os 4 COG finais (1985, 2008, 2015, 2025); sem bruto/, originais já apagados
```
(Segundo tema do MapBiomas, `pastagem_vigor`: 9 tiles em `bruto/`, mosaico ainda não gerado; existe só no notebook.)

## Decisão: manter como raster, não vetorizar

A 30m de resolução, uso do solo é fragmentado demais — vetorizar o país
geraria dezenas/centenas de milhões de polígonos. A pergunta típica ("% de
área por classe dentro da fazenda") é zonal statistics, que roda direto no
raster, sem precisar de vetor.

## `uso_do_solo/` — Status: convertido pra COG (2026-10-01)

4 anos baixados da Coleção 11 (1985, 2008, 2015, 2025), Brasil inteiro, um
arquivo por ano (não é um único multibanda).

⚠️ **CRS de origem era WGS84 (EPSG:4326)**, diferente do padrão do projeto
(SIRGAS2000/EPSG:4674) — mesma situação do SICAR. Reprojetado pra
EPSG:4674 nesta conversão, pra manter tudo no mesmo CRS.

Cada arquivo já vinha `Byte` (categórico, código de classe) e já tiled
(256×256) com LZW+PREDICTOR=2 — sem overviews. Convertido direto com
`gdalwarp -of COG`, fazendo reprojeção + geração de overviews no mesmo
comando:

```powershell
$env:PROJ_LIB = "C:\Program Files\QGIS 3.44.11\share\proj"
& "C:\Program Files\QGIS 3.44.11\bin\gdalwarp.exe" -t_srs EPSG:4674 -r near -of COG -co COMPRESS=LZW -co PREDICTOR=2 -co RESAMPLING=NEAREST -co BLOCKSIZE=256 <entrada>.tif <saida>_cog.tif
```

⚠️ **`-r near` e `-co RESAMPLING=NEAREST` são obrigatórios aqui** (não é
opcional/padrão) — como o valor do pixel é um **código de classe**, não
uma grandeza contínua, qualquer reamostragem por média/bilinear/cúbica
misturaria códigos de classes diferentes em números sem sentido, tanto na
reprojeção quanto na geração das overviews.

| Arquivo | Antes | Depois (COG, reprojetado) |
|---|---|---|
| 1985 | 646 MB | 1.091 MB |
| 2008 | 674 MB | 1.142 MB |
| 2015 | 687 MB | 1.164 MB |
| 2025 | 728 MB | 1.228 MB |

Cresceu (~65-70% a mais), não encolheu — esperado, é o mesmo trade-off já
documentado no TOPODATA: COG não comprime, adiciona overviews (dado extra
pra zoom rápido), e aqui não tem ganho de tipo de dado possível (já era
`Byte`, o menor tipo que existe).

**Validação**: comparado o valor de classe em pontos de amostra espalhados
(coordenadas reais, via `gdallocationinfo -wgs84`) entre original e
convertido, nos 4 anos — bateu exato em todos. Um dos pontos inclusive
mostrou mudança real de uso do solo entre os anos (classe 41→15→15), sinal
de que o dado em si está íntegro, não só a estrutura do arquivo.

Arquivos `Byte` originais (WGS84, sem overview) apagados depois da
validação.

## `pastagem_vigor/` — investigado (2026-10-01), ainda não processado

⚠️ **O "MG" no nome do arquivo não é Minas Gerais** — é código de produto/grid
do MapBiomas. Os 9 tiles (`pasture_vigor_c11_MG-<offset_x>-<offset_y>.tif`,
offsets 0/65536/131072 em X e Y, grade 3×3) cobrem o **Brasil inteiro**,
cada um 65536×65536 pixels, ~427MB somados.

Encontrado ao inspecionar:
- CRS: SIRGAS2000, mas como **EPSG:6674** (variante 3D), não o `4674` que o
  resto do projeto usa — horizontalmente deveria ser idêntico (mesmo
  datum), mas vale normalizar o rótulo na hora de processar.
- 1 banda só, `Description = classification_2025` — é só o ano de 2025,
  não tem série histórica como o `uso_do_solo`.
- Valores de 0 a 3 (`Byte`), sem `NoData` setado explicitamente — provável
  0 = fora de área de pastagem, 1/2/3 = classes de vigor baixo/médio/alto,
  mas **não achamos o CSV de legenda oficial desse produto específico**
  ainda (só temos legenda do `uso_do_solo`).

Pendente pra quando for processar: baixar/confirmar a legenda oficial de
classes, decidir se precisa de mosaico num arquivo só antes do COG (os 9
tiles já não se sobrepõem, então um `gdalbuildvrt` + `gdal_translate -of
COG` direto do VRT deve resolver sem reprocessar cada tile sozinho).
