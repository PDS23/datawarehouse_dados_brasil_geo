# incra/assentamentos — Projetos de assentamento do INCRA (polígonos, Brasil)

Coleta automatizada do **WFS público do Acervo Fundiário do INCRA** (sem login), uma camada por UF, para
`vetorial.incra_assentamentos`. Pipeline: `scripts/assentamentos.py`. Guia geral: `scripts_comuns/LEIAME_pipelines.md`.

```
incra/assentamentos/
├── config.yaml                 URL do WFS, camada por UF, campos, caixa do Brasil
├── sql/01_esquema.sql          dim.fontes (INCRA) + vetorial.incra_assentamentos (DDL, por administrador)
├── sql/02_estado_espacial.sql  migração (id_estado_camada x id_estado) para quem criou a tabela antes dela
├── scripts/assentamentos.py    coleta e carga
└── bruto/wfs_incra/            assentamentos_<uf>.gml.gz + manifesto (fora do git)
```

Este pipeline **substitui** o recorte antigo do Semiárido (`incra/bruto/assentamentos/Assentamentos-SAB-INCRA.shp`,
2.429 polígonos, vindo do INSA): a camada nova cobre o Brasil todo (menos o Pará, ver abaixo).

## Pará: vem do shapefile, não do WFS

O servidor do INCRA **falha de forma persistente para a camada do Pará** (`assentamentos_pa`: "msPostGISLayerGetItems():
Query error", 100% das tentativas em 2026-10-15; as outras 26 UFs respondem em ~1 s). O erro é do servidor deles.
O Pará (1.082 polígonos) foi carregado pelo **shapefile do Acervo Fundiário** (`certificacao.incra.gov.br/csv_shp/export_shp.py`,
formulário `selectshp=assent`, `selectuf=PA`), baixado à mão pelo usuário em 2026-10-15:

```powershell
... run --rm etl incra/assentamentos/scripts/assentamentos.py --zip PA=incra/assentamentos/bruto/export_shp/assentamento_pa.zip
```

- **Esse caminho exige login gov.br** (o POST sem sessão devolve a página de login): **não é automatizável**; é a alternativa manual
  para qualquer UF cujo WFS falhe. O script imprime essa dica sempre que uma UF falha.
- O shapefile **não traz o gid do INCRA**: `gid_incra` vira um número **negativo** derivado de `cd_sipra` + geometria (+ nº da ocorrência:
  o INCRA publica polígonos idênticos repetidos). Estável enquanto o polígono não mudar. Se o WFS do Pará voltar a funcionar, a
  próxima carga completa insere os polígonos com gid real e os de gid negativo ficam com `visto_em` antigo e entram no aviso
  "sumiram" (não se apaga sozinho; remova com `DELETE ... WHERE gid_incra < 0 AND id_estado_camada = 15`, depois de conferir).
- Rodar o script **sem** `--zip` continua tentando o WFS do Pará e termina com código 3 enquanto ele falhar.

Cobertura hoje: **27 UFs, 7.525 polígonos, 7.490 projetos** (6.443 do WFS + 1.082 do shapefile do Pará).

## Modelo

`vetorial.incra_assentamentos`: **uma linha por polígono** (`gid_incra`, único; o INCRA não garante que seja estável).

- **Um projeto (`cd_sipra`) pode ter vários polígonos** (22 códigos se repetem). `area_declarada_ha` é a área do
  **projeto** e repete em cada polígono dele: **não some por linha**. `area_calc_ha` é a área do polígono (vazia em 238).
- `id_estado_camada` = camada do INCRA de onde veio; **`id_estado` = UF onde o polígono está** (ponto na superfície
  dentro de `dim.estados`). **Use `id_estado`.** A camada "DF" é a jurisdição da superintendência do DF: 204 de seus 208
  polígonos estão em GO (109) e MG (95); a de PE traz 11 polígonos na BA, etc. (conferido pela posição).
- `municipio`: texto do INCRA (MAIÚSCULAS, sem UF), sem vínculo com `dim.municipios` (um projeto pode ocupar mais de
  um município; para o vínculo, cruze a geometria).
- `fase`: código do SIPRA (3, 4, 5, 6, 7 e 10); **o servidor não traz a descrição** e eu não a inventei.
  `sr` e `descricao_fase` vêm vazios em todas as feições e não são gravados. `cd_sipra` com prefixo `MF` (268, em PE) é do próprio INCRA.
- `capacidade_familias` e `num_familias` (famílias assentadas; 76 com zero). `data_criacao` e `data_obtencao` (no INCRA vêm `dd/mm/aaaa`).
- `visto_em`: última coleta em que o polígono ainda existia no servidor. **Nunca se apaga:** polígono que sumir do
  INCRA fica na tabela com `visto_em` antigo e é listado no aviso da carga. `importado_em` = última vez que a linha **mudou**.

## Geometria

- O WFS entrega as coordenadas rotuladas **WGS84 (EPSG:4326)** (o `.prj` do recorte antigo também diz WGS84). Gravamos como
  **SIRGAS 2000 (4674)** sem transformar, para casar com o resto do banco (diferença abaixo de 1 m).
- O parser (`dwlib/wfs.py`) é próprio: o leitor GML do GDAL levava ~2 min só para a Bahia; o parser lê o Brasil inteiro em 2 s.
  O WFS 1.1.0 devolve lat/lon; o parser troca para lon/lat. Todos os vértices ficam dentro da caixa do Brasil (o script rejeita e lista os que não).
- **72 polígonos (1,1%) vêm inválidos do INCRA** (30 autointerseção, 19 autointerseção de anel, 23 "poucos pontos").
  **Não foram corrigidos**: ficam como o INCRA publica. Para análise espacial robusta use `ST_MakeValid(geom)` ou filtre `ST_IsValid(geom)`.

## Licença

O WFS declara `AccessConstraints: vedado o uso comercial`. Registrado em `catalogo.datasets.licenca`. Confirmar os termos
antes de redistribuir ou usar em produto comercial.

## Como rodar (a partir de D:\data_warehouse\infra)

```powershell
# todas as UFs (~1 min); termina com código 3 enquanto o Pará falhar
docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl incra/assentamentos/scripts/assentamentos.py
# só algumas UFs, ou ensaio sem gravar
... run --rm etl incra/assentamentos/scripts/assentamentos.py --ufs PR,SC
... run --rm etl incra/assentamentos/scripts/assentamentos.py --simular
```

Reexecutar é seguro: só regrava o que mudou (verificado: segunda execução = 0 novos, 0 atualizados).

## Consulta típica

```sql
-- projetos e famílias por estado onde o polígono está (um projeto conta uma vez)
SELECT e.sigla_uf, count(DISTINCT a.cd_sipra) AS projetos, sum(a.num_familias) AS familias
FROM vetorial.incra_assentamentos a JOIN dim.estados e USING (id_estado)
GROUP BY 1 ORDER BY 2 DESC;
```
