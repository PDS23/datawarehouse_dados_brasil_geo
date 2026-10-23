# sicar/ — SICAR (Sistema Nacional de Cadastro Ambiental Rural)

> ## ⚠️ HISTÓRICO — superado em 2026-10-20
> `vetorial.sicar_imoveis` foi **reconstruída do zero pelo WFS público do CAR** e é atualizada só por ele.
> **Documentação atual: [LEIAME_sicar_imoveis.md](LEIAME_sicar_imoveis.md).**
> O texto abaixo descreve a carga antiga por GeoPackages (27/09 a 01/10/2026) e é mantido só como registro. Os scripts dessa
> época (`importar_estados.py`, `anomalias_geometria.sql`, `quarentena_geometria.sql`) **foram removidos** em 20/10/2026, e a
> tabela antiga (`sicar_imoveis_gpkg_antiga`) foi apagada. As anomalias de geometria agora são tratadas na própria coleta
> (`geom_anomala`, texto original em `geom_origem_texto`).

## Organização (atual)

```
sicar/
sicar/imoveis/                    (ver LEIAME_sicar_imoveis.md; os GeoPackages da carga antiga já não estão no disco)
```

## Fonte

Perímetros de imóveis rurais (camada "Área do imóvel") baixados direto do SICAR,
um GeoPackage por estado (26 UF + DF), já em `bruto/`. CRS de
origem: **WGS84 (EPSG:4326)** — único dataset do projeto que não vem em
SIRGAS2000, por isso o import reprojeta pra EPSG:4674 (`-t_srs`).

## Status: os 27 estados estão no PostGIS (2026-10-01)

Tabela `vetorial.sicar_imoveis` no banco `data_warehouse`:
**8.360.953 imóveis**, todos os 27 estados, `id_estado`/`id_municipio`
referenciados por FK (`dim.estados`, `dim.municipios`) desde a criação —
nenhum retrofit tardio como aconteceu com o PRODES.

Estrutura pensada pra histórico (SCD tipo 2): toda linha tem
`vigente_desde`/`vigente_ate` — `vigente_ate IS NULL` = versão atual. Quando
o SICAR for atualizado (próxima vez que baixarmos um estado de novo),
comparar por `cod_imovel` + `dat_atuali`: imóvel novo → insere; sumiu →
fecha `vigente_ate`; mudou → fecha a versão antiga e insere a nova. Um
índice único parcial (`idx_sicar_imoveis_atual`, só em `cod_imovel` WHERE
`vigente_ate IS NULL`) garante no banco que nunca existem duas versões
"atuais" do mesmo imóvel ao mesmo tempo.

`id_municipio` vem direto do `cod_imovel` (`split_part(cod_imovel,'-',2)`) —
o próprio SICAR já embute o código IBGE do município no meio do código do
imóvel (ex.: `AC-1200013-...` → `1200013` = Acrelândia/AC), então não
precisou casar por nome de texto.

## Validação final

- `count(*) = 8.360.953`, 27 estados
- `id_estado`: 0 linhas nulas
- `id_municipio`: 64 linhas nulas (ver "Pegadinha: município sem código
  IBGE válido" abaixo — caso conhecido e aceito, não bloqueia nada)
- `ST_IsValid(geom)`: 356 geometrias inválidas (auto-interseção, anel se
  cruzando, poucos pontos) — defeito de topologia no próprio dado de
  origem do SICAR, 0,004% do total, não corrigido (ver nota abaixo)

## ⚠️ Pegadinha: `cod_imovel` duplicado dentro do próprio arquivo de origem

Ao tentar reimportar os estados que tinham ficado incompletos (ver seção
"Incidente" abaixo), vários travaram com erro de violação do índice único
em `cod_imovel` **mesmo depois de apagar qualquer dado residual nosso**.
Investigado: o GeoPackage de origem do GO, por exemplo, tem 240.907
feições mas só 240.896 `cod_imovel` distintos — 11 duplicatas genuínas,
confirmadas idênticas em todos os atributos (mesma área, mesma data, mesmo
status). Mesmo tipo de particularidade que já tínhamos visto no PRODES (13
feições repetidas entre camadas da Amazônia).

**Fix**: a consulta de import (`SQL_SELECT_ORIGEM` no script) já filtra
`WHERE id IN (SELECT MIN(id) FROM AREA_IMOVEL GROUP BY cod_imovel)`,
mantendo só 1 linha por `cod_imovel` na origem, antes mesmo de chegar no
banco.

## ⚠️ Pegadinha: município sem código IBGE válido

64 imóveis do Mato Grosso trazem `municipio = "Boa Esperança do Norte"`
com código embutido `5101837` — esse código **não existe** em
`dim.municipios` (base com os 5.572 municípios oficiais do IBGE,
confirmada contra o total oficial de 141 municípios de MT). Não é erro
nosso: é um nome/código que o SICAR usa internamente e que não corresponde
a um município oficialmente reconhecido pelo IBGE.

**Fix**: o `UPDATE` que popula `id_municipio` faz `JOIN` contra
`dim.municipios` em vez de um cast direto e cego do código extraído —
linhas sem correspondência ficam `NULL` (sem travar a importação do resto
do estado), em vez de violar a FK e abortar o `UPDATE` inteiro. Ver
`importar_estados.py`, função `importar_estado`.

## ⚠️ Pegadinha: captura de saída do `ogr2ogr` quebrando no meio do import

O script original (antes da correção) usava `subprocess.run(..., text=True)`
sem especificar `encoding` — no Windows, isso usa a codificação do console
(cp1252) pra decodificar a saída do `ogr2ogr`, que vem em UTF-8 (nomes de
município acentuados). Um byte UTF-8 que não existe em cp1252 derruba a
thread que lê a saída (`UnicodeDecodeError`), e isso **interrompeu o
`ogr2ogr` no meio da transferência silenciosamente** — o processo
continuava rodando (não travava, não dava erro visível), mas parava de
inserir linhas no meio do lote, e o script seguinte linha reportava "OK"
porque só checava o código de saída, não o total real.

**Descoberto por acaso**: vários estados ficaram com contagem suspeita
terminando em "999" redondo (ex.: `99999`, `199999`, `499999`) — sinal de
corte exato no limite de lote do COPY do GDAL (100.000 linhas).

**Fix**: todo `subprocess.run` no script agora passa
`encoding="utf-8", errors="replace"` explicitamente. E mais importante: o
script **não confia mais só no código de saída** — depois de importar,
compara o total de `cod_imovel` distintos na origem (via `ogrinfo -sql`)
contra o total que realmente entrou no banco, e avisa claramente se não
bater, em vez de reportar "OK" errado.

## Sobre as 356 geometrias inválidas

Não corrigidas por enquanto — são erros de topologia (auto-interseção,
anéis se cruzando) no desenho original do polígono, feito por quem
cadastrou o imóvel no SICAR. `ST_MakeValid()` resolveria a maioria, mas
fica pra quando algum processamento real (overlay, `ST_Intersection`) com
essas 356 linhas específicas precisar funcionar — nesse momento,
`ST_MakeValid()` na hora da consulta é suficiente, não precisa alterar a
tabela armazenada.

## ⚠️ Anomalia conhecida: 2 imóveis com coordenadas fora do Brasil (verificado em 2026-10-13)

Dois registros de `vetorial.sicar_imoveis` têm geometria com coordenadas que não
correspondem a nenhum sistema de referência válido. Eles estão **assim no arquivo
original do SICAR** (conferido em `MA_AREA_IMOVEL.gpkg`, 412.107 registros, e
idênticos no banco e no WFS): não é erro da importação. **A geometria foi anulada
(`geom = NULL`) em 2026-10-13, por decisão do usuário; todos os outros atributos foram
mantidos** e a geometria original ficou guardada em
`catalogo.anomalias_geometria.geom_original` (EWKT, reversível).

| `cod_imovel` | `id` | Município | `num_area` | Extensão original (x, y) |
|---|---|---|---|---|
| `MA-2111300-045ECDCB05174B03A89C8081BA13A1BA` | 2419895 | São Luís (2111300) / MA | 16.870,24 ha | x 44.280.001 a 44.888.087; y 2.654.072 a 239.074.544 |
| `SE-2802908-9443714ADF004910A5E43B994F08A011` | 11074433 | Itabaiana (2802908) / SE | 0,85 ha | x 89,25; y 0 |

O do Maranhão é um retângulo de 5 vértices que o `ST_IsValid` considera válido, só
que fora da Terra. As outras 412.106 feições do Maranhão estão normais (a maior
seguinte mede 0,61 grau). No Brasil inteiro são só esses 2 em 8.360.953.

**Efeito antes da quarentena:** a extensão calculada da camada (zoom na camada no QGIS,
`ST_Extent`, extensão gravada num GeoPackage exportado) virava uma faixa vertical gigante
e o resto desaparecia. Pelo WFS isso não aparecia, porque o GeoServer anuncia uma
extensão fixa (a caixa do Brasil), mas os dados eram os mesmos. Depois da quarentena, a
extensão do Maranhão é `-48,75 -10,28` a `-41,80 -1,05` e a de qualquer estado é normal.
Os 2 imóveis continuam na tabela de atributos, só não aparecem no mapa.

**Como lidar (e repetir a cada atualização do SICAR):**

- Registro e quarentena: `infra/postgres/anomalias_geometria.sql` (detecta; cria/atualiza
  `catalogo.anomalias_geometria`; idempotente, ~20 s) e depois
  `infra/postgres/quarentena_geometria.sql` (anula a geometria dos casos da fila; **simula
  por padrão** e só grava com `-v confirmar=1`; aborta se a fila tiver mais de 10
  registros). **Rodar os dois depois de cada importação do SICAR**, porque uma nova
  versão pode trazer de novo a mesma geometria defeituosa.
- Para desfazer: `UPDATE ... SET geom = ST_GeomFromEWKT(geom_original)` (instrução no
  próprio script). O arquivo original do SICAR também tem a geometria.
- Um filtro de extensão como `AND geom && ST_MakeEnvelope(-75, -35, -28, 6, 4674)` deixa
  de ser necessário para esses 2 casos, mas continua sendo uma boa proteção contra novos.
- O aviso também está em `catalogo.datasets` (SICAR) e no resumo da camada
  `dw:sicar_imoveis` no GeoServer.
- Nota de método: o QGIS pagina o WFS, então exportar o Maranhão pelo WFS **não** corta
  em 100.000 feições (o limite vale por pedido); o arquivo exportado tinha as 412.107.

## Scripts disponíveis

```
python scripts\importar_estados.py    # importa a lista de siglas em ESTADOS
```

Pra reimportar um estado específico (ex.: numa atualização futura), edite
a lista `ESTADOS` no topo do script. O índice único em `cod_imovel` (WHERE
`vigente_ate IS NULL`) impede duplicata automática — se tentar reimportar
um estado que já está completo, vai dar erro de chave duplicada (esperado,
sinal de proteção funcionando, não de bug).

## Próximo passo

SICAR está completo no PostGIS. Próximo passo de verdade: desenhar o
pipeline de atualização periódica (SCD2, comparando `dat_atuali`) —
candidato natural pra aprender Airflow (ver ROADMAP.md).
