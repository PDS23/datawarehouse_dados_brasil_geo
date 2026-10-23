# elevacao/topodata — TOPODATA (INPE): altitude e declividade, via BDC/STAC

> **Documento restaurado em 2026-10-20** a partir do texto do notebook (escrito em 2026-09/10). Estado em relação ao
> padrão de fontes (ARQUITETURA.md): o download tem script (`scripts/baixar_topodata_*.py`); o processamento (mosaico,
> declividade, COG) foi feito por comandos soltos descritos abaixo e **ainda não virou script reexecutável nem há
> `config.yaml`**. Os rasters de `processado/` são montados no GeoServer (`infra/docker-compose.stack.yml`) e citados em
> `catalogo.datasets` pelo caminho `elevacao/topodata/processado/...`: **não mover essa pasta sem ajustar os dois**.
> O `bruto/` e o `processado/` não estão no git; o `processado/` está no Drive para compartilhar com a equipe.

## Fonte atual (2026)

O TOPODATA saiu do antigo host `dsr.inpe.br` (domínio fora do ar / DNS não
resolve mais) e passou a ser distribuído pelo **BIG (Banco de Imagens
Geocientíficas) do INPE**, através da API STAC do Brazil Data Cube:

- Coleção: `https://data.inpe.br/bdc/stac/v1/collections/topodata-1`
- Itens (paginado, 556 folhas cobrindo o Brasil):
  `https://data.inpe.br/bdc/stac/v1/collections/topodata-1/items?limit=100`
- Cada folha (ex.: `00S465`) tem um asset por produto, com link direto de
  download em COG (Cloud Optimized GeoTIFF):
  `https://data.inpe.br/bdc/data/topodata/v001/<lat><NS>/<lon>/<folha><PRODUTO>.tif`

Produtos disponíveis por folha (chave do asset no STAC):

| Chave | Produto                                   | Unidade / tipo         |
|-------|--------------------------------------------|------------------------|
| ZN    | Altitude                                    | metros, contínuo (float32) |
| SN    | Declividade                                 | **% (não graus!)**, contínuo (float32) |
| SA    | Declividade em classes — Marques 1971       | categórico (uint8)     |
| SB    | Declividade em classes — Lepsch 1991        | categórico (uint8)     |
| SC    | Declividade em classes — Embrapa 1999       | categórico (uint8)     |
| ON    | Orientação de vertente (aspect)             |                        |
| OC    | Orientação em octantes                      |                        |
| HN    | Curvatura horizontal (contínua)             |                        |
| H3/H5 | Curvatura horizontal em 3/5 classes         |                        |
| VN    | Curvatura vertical (contínua)               |                        |
| V3/V5 | Curvatura vertical em 3/5 classes           |                        |
| FT    | Forma de terreno                            |                        |
| DD    | Divisores e talvegues                       |                        |
| RS    | Relevo sombreado (hillshade)                |                        |

Tamanhos totais medidos direto na API (soma de `bdc:size`, Brasil inteiro,
556 folhas): SN ~49,9 GB, ZN ~40,0 GB, SA ~1,04 GB, SB ~1,70 GB, SC ~1,36 GB.

⚠️ Já tentamos baixar o SC (declividade classificada) para o Brasil inteiro,
mas ele foi **apagado**: classes fixas do Embrapa não servem para calcular
faixas de declividade personalizadas (ex.: 11°-22°) — uma vez que o pixel virou
"classe 3" o valor contínuo original se perde. Para faixas customizadas em
graus é preciso do **produto contínuo (ZN + `gdaldem slope`, ou SN convertido
de % para graus)** — ver seção abaixo.

## Organização da pasta

```
topodata/
├── LEIAME_topodata.md
├── scripts/
│   ├── baixar_topodata_stac.py      (Brasil inteiro, por produto)
│   └── baixar_topodata_regiao.py    (recorte por bbox, ex. RS+SC)
├── bruto/                            (folhas originais baixadas do STAC, sem alteração)
│   └── rs_sc/
│       └── altitude_zn/              (41 .tif, produto ZN)
└── processado/                       (mosaicos, reprojeções, derivados)
    └── rs_sc/
        ├── rs_sc_altitude.vrt
        ├── rs_sc_declividade_graus.tif
        └── rs_sc_declividade_pct.tif
```

Padrão pra novas regiões/produtos: `bruto/<regiao>/<produto>/` pros arquivos
originais, `processado/<regiao>/` pros derivados (mosaico, reprojeção,
declividade, recortes por faixa). Isso é o mesmo padrão que o
[ROADMAP.md](../../ROADMAP.md) prevê generalizar pro resto do data warehouse
conforme mais datasets forem entrando.

## O que está baixado hoje

Só a região de **Rio Grande do Sul + Santa Catarina** (não o Brasil inteiro —
os produtos contínuos ZN/SN pesam 40-50GB no país inteiro, inviável por
enquanto). Fluxo usado:

1. `bruto/rs_sc/altitude_zn/` — 41 folhas do produto **ZN** (altitude,
   metros) que cobrem a bounding box de RS+SC (~2,9 GB). Baixado com
   `scripts/baixar_topodata_regiao.py`.
2. `processado/rs_sc/rs_sc_altitude.vrt` — mosaico virtual das 41 folhas,
   ainda em WGS84 (graus lat/lon).
3. (passo intermediário, **arquivo não guardado em disco** — ver nota
   abaixo) mosaico **reprojetado** para **SIRGAS 2000 / UTM zone 22S
   (EPSG:31982)**, resolução 30m, resample bilinear. Passo necessário:
   `gdaldem slope` presume que as unidades horizontais e verticais são
   iguais (metros), então rodar direto sobre um raster em graus (WGS84) dá
   declividade errada. UTM 22S é o sistema métrico padrão usado pra RS/SC
   (não é perfeito nas bordas extremas do estado que caem na zona 21S, mas é
   a prática comum pra uma análise regional).
4. `processado/rs_sc/rs_sc_declividade_graus.tif` (~2,4 GB) — declividade
   contínua em **graus** (0° a ~77° no recorte), gerada com `gdaldem slope`
   (algoritmo Horn, default) sobre o raster projetado.
5. `processado/rs_sc/rs_sc_declividade_pct.tif` (~2,4 GB) — a mesma
   declividade contínua, em **porcentagem** (0% a ~428% no recorte). Gerada
   a partir do arquivo em graus por conversão matemática direta
   (`% = tan(graus × π/180) × 100`), não recalculada do zero a partir da
   elevação — dá o mesmo resultado (é a mesma superfície, só outra unidade)
   e evita reprocessar a reprojeção UTM.

> **Nota (2026-09-23)**: o intermediário reprojetado (`rs_sc_altitude_utm22s.tif`)
> e o exemplo de faixa personalizada 11°-22° que existiam antes não estão
> mais na pasta. Se precisar do intermediário reprojetado de novo, é só
> repetir o passo 3 (`gdalwarp -t_srs EPSG:31982`) a partir do
> `rs_sc_altitude.vrt`, que continua aqui.

## ✅ Conversão Int16 + COG concluída (2026-10-01)

Os dois rasters contínuos de declividade de RS+SC foram convertidos de
Float32 pra Int16 escalado + perfil COG (tiled + overviews), usando o
driver `COG` nativo do GDAL (`gdal_calc.py ... --format=COG`, tiling e
overviews gerados no mesmo comando, sem precisar de `gdaladdo` separado):

| Arquivo | Escala usada | Antes (Float32) | Depois (Int16+COG) |
|---|---|---|---|
| `rs_sc_declividade_graus_int16cog.tif` | grau × 100 | ~2,4 GB | 1.256 MB |
| `rs_sc_declividade_pct_int16cog.tif` | % × 10 | ~2,4 GB | 918 MB |

⚠️ **Escalas diferentes entre os dois arquivos**: graus usa ×100 (igual ao
teste original), mas porcentagem usa ×10 — escalar % por 100 estouraria o
limite do `Int16` (o valor máximo do recorte, 427,8%, vezes 100 passa de
32.767). Qualquer consulta/expressão sobre esses arquivos precisa dividir
pelo fator certo antes de interpretar o valor como grau ou % de verdade.

Validado: `gdalinfo -stats` nos arquivos novos bate exatamente com o
original multiplicado pela escala (ex.: máximo 76,84° vira 7684; média
8,725% vira 87,25), mesmo `NoData=-9999`, mesmo `VALID_PERCENT`.

Comando usado (ajustar `-A`/`--outfile`/escala/`--type` pra outro raster):
```powershell
"C:\Program Files\QGIS 3.44.11\apps\Python312\python.exe" "C:\Program Files\QGIS 3.44.11\apps\Python312\Scripts\gdal_calc.py" -A <entrada.tif> --outfile=<saida_int16cog.tif> --calc="(A!=-9999)*(A*<escala>) + (A==-9999)*(-9999)" --NoDataValue=-9999 --type=Int16 --format=COG --co COMPRESS=DEFLATE --co PREDICTOR=2
```
(lembrar do `$env:PROJ_LIB` antes, mesmo conflito de sempre com o QGIS)

Arquivos Float32 originais mantidos por enquanto (só apagar depois de
confirmar visualmente no QGIS que os novos estão corretos).

## ✅ Estilo de simbologia (QGIS) confirmado funcionando (2026-10-01)

Dois arquivos `.qml` prontos, testados e confirmados carregando sem erro
no QGIS 3.44.11, com a classificação de declividade clássica da EMBRAPA (6
classes, verde→vermelho):

- `processado/rs_sc/estilo_declividade_graus.qml` (limiares em grau×100)
- `processado/rs_sc/estilo_declividade_pct.qml` (limiares em %×10)

Servem de **modelo pra qualquer raster contínuo novo** que precise de
simbologia por faixa de classe — copiar um dos dois, trocar `classificationMax`
pro valor máximo real do novo raster, e ajustar os `<item value=... label=...
color=...>` pros limiares/cores desejados (`value` é o limite **superior**
de cada classe, em `DISCRETE`; o último item usa `value="inf"`).

Carregar no QGIS: camada → aba Simbologia → ícone "Estilo" (canto inferior
esquerdo) → "Carregar Estilo...".

## Como gerar outra faixa personalizada (ex.: 5°-15°, >30%, etc.)

Usando o raster contínuo em graus (`rs_sc_declividade_graus.tif`) ou em %
(`rs_sc_declividade_pct.tif`), o que for mais conveniente pro pedido — não
precisa baixar nada de novo:

**No QGIS** (mais simples): Calculadora Raster (`Raster → Calculadora
Raster…`), expressão tipo:
```
("rs_sc_declividade_graus@1" >= 5) * ("rs_sc_declividade_graus@1" <= 15)
```

**Via linha de comando** (GDAL vem junto do QGIS instalado; o `python.exe` do
sistema não tem os bindings do GDAL — use o Python do próprio QGIS):
```
"C:\Program Files\QGIS 3.44.11\apps\Python312\python.exe" ^
  "C:\Program Files\QGIS 3.44.11\apps\Python312\Scripts\gdal_calc.py" ^
  -A rs_sc_declividade_graus.tif ^
  --outfile=rs_sc_declividade_5a15graus.tif ^
  --calc="(A>=5)*(A<=15)" ^
  --NoDataValue=255 --type=Byte --co COMPRESS=DEFLATE --co TILED=YES
```

## Baixar outra região ou o Brasil inteiro depois

Use `scripts/baixar_topodata_regiao.py` (edite `MINLON/MAXLON/MINLAT/MAXLAT`,
`PRODUTO` e o `OUTDIR` no topo do arquivo, seguindo o padrão
`bruto/<regiao>/<produto>/`) para outro estado/bbox, ou
`scripts/baixar_topodata_stac.py` (edite `PRODUTO` e `OUTDIR`) para o Brasil
inteiro sem recorte. Ambos paginam a API do STAC sozinhos, pulam arquivos já
baixados com o tamanho certo, e tentam de novo em caso de falha de rede.

Depois de baixar ZN de uma nova área, repita os passos 2-4 acima
(`gdalbuildvrt` → `gdalwarp -t_srs <UTM da região>` → `gdaldem slope`) — troque
o EPSG da UTM pela zona correta da região (ex. UTM 23S para SP/RJ).

## Sobre o produto SN (declividade contínua em %)

Se preferir usar o SN do INPE em vez de calcular via `gdaldem slope` a partir
do ZN: SN vem em **porcentagem**, não graus. Para converter para graus na
calculadora raster do QGIS:
```
atan("SN@1" / 100) * 180 / 3.14159265359
```
Os dois caminhos (SN convertido, ou ZN + gdaldem slope) devem dar resultados
próximos, mas não idênticos (algoritmos de derivação diferentes).
