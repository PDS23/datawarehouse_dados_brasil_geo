# sicar/imoveis — Imóveis rurais do SICAR (CAR): fonte única de `vetorial.sicar_imoveis`

Desde **2026-10-20**, `vetorial.sicar_imoveis` foi **reconstruída do zero** a partir do **WFS público do CAR**
(`geoserver.car.gov.br`, sem CAPTCHA e sem login) e é atualizada **só por ele**: uma fonte e uma metodologia para a tabela
inteira (rastreabilidade). Carga inicial e atualização são o mesmo comando (reconciliar uma UF inteira).
Pipeline: `scripts/atualizar_imoveis_sicar.py`. **Roda só sob demanda: `--ufs` é obrigatório.**
O dado é "o retrato atual do cadastro" (sem ano de referência): o banco espelha o CAR e guarda versões, não edições anuais.
O dado é baixado pelo serviço WFS público do CAR (ver "Como baixa"); WFS é só o protocolo, a fonte é o CAR.

```
sicar/imoveis/
├── LEIAME_sicar_imoveis.md      este arquivo
├── HISTORICO.md                 métodos anteriores (carga por GeoPackage, 2026-09) e mudanças de método
├── config.yaml                  URL, camada por UF, agentes, tolerâncias, caixa do Brasil
├── sql/01_tabela.sql            tabela (em sicar_novo), catalogo.coletas, coletas_duplicados, mapa_colunas
├── sql/02_indices_chaves.sql    índices e chaves estrangeiras depois da carga
├── sql/03_troca_unica.sql       a troca feita em 20/10 (nova assume o nome; antiga guardada); não se repete
├── scripts/atualizar_imoveis_sicar.py
└── bruto/                       logs e dados baixados (fora do git e do Drive)
```

## Estado em 2026-10-20

- **8.547.089 imóveis** em 27 UFs (AT 7.567.002; PE 756.167; **CA cancelados 165.202**; SU 58.717; RE 1), 8,0 GB.
- A carga antiga (pacotes GeoPackage por estado, `sicar_imoveis_gpkg_antiga`, 12 GB) foi **apagada em 2026-10-20** com
  aprovação do usuário. Backup de retorno: `20261020-164457-pre-troca-sicar-wfs` (D: e Drive).
- As tabelas `resultados.desmatamento_imovel` e `..._controle` foram **apagadas na troca** (apontavam para os ids antigos):
  recriar com `analises/desmatamento_imovel/scripts/desmatamento_imovel.ps1 -UF XX` (metodologia em `analises/desmatamento_imovel/LEIAME_desmatamento_imovel.md`).
- Camada do GeoServer `dw:sicar_imoveis` recriada (`publicar_geoserver.py --recriar sicar_imoveis`); os filtros de sempre
  (`cod_estado = 'AC' AND vigente_ate IS NULL`) funcionam.

## Como baixa (por que é rápido)

Paginar a UF inteira é inviável (BA: 12 a 55 s por página). O script **fatia por município** (`CQL cod_municipio_ibge=...`,
0,4 a 0,8 s por página) e usa **vários agentes** em paralelo (`--paralelo`, padrão 4, máximo 6). O que não cair em município
nenhum da dimensão vem por um filtro "NOT IN" (POST; GET longo dá erro 431). Confere o total contra o anunciado
(`resultType=hits`). Velocidade medida: ~8 a 10 mil imóveis/s; as 27 UFs levam uns 25 min (BA 4 min, MG 5,5 min).

## Como grava (uma transação por UF)

Compara com as versões **vigentes** (`vigente_ate IS NULL`):
- **novos** entram; **alterados** (qualquer campo da fonte ou a geometria) fecham a versão antiga e inserem a nova;
- **ausentes** do WFS têm a versão **fechada** (o banco é espelho do WFS; nada é apagado). Trava: passando de 10% da UF aborta
  (`--aceitar-queda` libera);
- **inalterados**: nada. Segunda execução seguida = 0 novos, 0 alterados (verificado);
- **reabertos** (regra de 2026-10-21): imóvel que sumiu do WFS e **volta idêntico** à última versão fechada tem **essa versão
  reaberta** (`vigente_ate` volta a NULL, mesmo `id`, `reaberto_em` registra a data) em vez de ganhar uma versão nova; assim os
  resultados já calculados com aquele `id` continuam valendo. Se voltar **diferente**, entra uma versão nova e a antiga continua
  fechada. Sempre existe no máximo uma versão vigente por `cod_imovel` (índice único). Testado em cópia do Acre: 3 reabertos,
  nenhuma duplicada (`sql/04_reabertura.sql` cria a coluna).
Cada UF coletada vira uma linha em `catalogo.coletas` (a última por UF: `catalogo.v_ultima_coleta`; coluna `reabertos`).

**Retenção:** versões fechadas de imóveis que o WFS retirou e não voltaram são apagadas depois de um prazo (padrão 365 dias) pela
rotina `infra/scripts/limpar_versoes_fechadas.py` (config `infra/retencao.yaml`; só relata sem `--apagar`; não agendada).

## Colunas (nomes nossos; origem em `catalogo.mapa_colunas`)

`ind_status`←status_imovel, `des_condic`←condicao, `num_area`←area, `dat_atualizacao`←data_atualizacao,
`cod_estado`←uf, `id_municipio`←cod_municipio_ibge, `mod_fiscal`←m_fiscal, `ind_tipo`←tipo_imovel; `cod_imovel`, `municipio`
e `dat_criacao` iguais; `fid_wfs` = id da feição no WFS. As datas vêm **com hora** (`timestamptz`). Controle: `vigente_desde`,
`vigente_ate`, `coletado_em`, `geom_anomala`, `geom_origem_texto`. **Descartadas** (não existem no WFS): `num_retific`
(3,12 milhões de imóveis tinham valor > 0 no pacote antigo) e `nom_tema` (constante).

## O que a fonte tem de peculiar (medido em 2026-10-20)

- **`cod_imovel` repetido** (retificação em andamento: a feição nova convive com a velha): 10 casos na carga (MS 2, MT 3,
  GO 3, PI 1, MG 1). **Regra: fica a feição de maior `data_atualizacao` (nula = a menor); empate, o maior identificador.**
  As descartadas ficam em `catalogo.coletas_duplicados`. A regra bate com os demonstrativos do SICAR nos 5 casos conferidos
  (um deles mostra a feição *mais antiga*, por isso não vale "maior identificador").
- **`dat_criacao` do WFS é a criação do registro da feição**, não a data de inscrição: em imóvel retificado reflete a
  retificação. A "data da inscrição" e a "data da última retificação" do demonstrativo **não existem no WFS**.
- **`dat_atualizacao` nula em 3,9 milhões (46%)**: 100% nula em RS, PR, SP, SC, PE, PI e RO; a fonte não preenche.
  Por isso a atualização é por reconciliação da UF, não por data.
- **Geometria**: 4.813 inválidas na fonte (autointerseção), mantidas como entregues (use `ST_MakeValid` na análise);
  **2 anômalas** (MA e SE, coordenadas fora do Brasil): `geom` NULL, `geom_anomala = true`, texto original em `geom_origem_texto`.
- **29 imóveis com `uf` diferente do prefixo do código**: o UF e o município do WFS concordam entre si (a camada segue a
  localização; o prefixo é onde o cadastro foi feito).
- **Status `RE`** (1 imóvel, GO): código desconhecido, mantido como a fonte entrega (significado NÃO VERIFICADO).
- A fonte é **ao vivo** e o status "pendente" cresce todo dia (CAR reclassificando); cada mudança de status vira versão nova.

## TLS legado

`geoserver.car.gov.br` só aceita TLS 1.2 com cifras antigas, que o OpenSSL 3 do contêiner recusa por padrão. `dwlib/http.py`
afrouxa **só a lista de cifras** nessa conexão; o certificado **continua verificado**. Use apenas para dados públicos.

## Como rodar (a partir de D:\data_warehouse\infra)

```powershell
# ensaio: baixa, compara e relata, sem gravar
docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl sicar/imoveis/scripts/atualizar_imoveis_sicar.py --ufs AC --simular
# gravar (uma ou várias UFs)
... run --rm etl sicar/imoveis/scripts/atualizar_imoveis_sicar.py --ufs AC,RO
```
Depois de reconciliar uma UF, recalcule o desmatamento dos pendentes: `analises\desmatamento_imovel\scripts\desmatamento_imovel.ps1 -UF XX`.

## Removido em 2026-10-20 (era do tempo dos pacotes GeoPackage)

`sicar/scripts/importar_estados.py`, `infra/postgres/anomalias_geometria.sql`, `infra/postgres/quarentena_geometria.sql`,
`sicar/imoveis/sql/01_permissoes.sql` (nome antigo) e a tabela `vetorial.sicar_imoveis_gpkg_antiga`. Anomalias de geometria agora são
tratadas na própria coleta. Se for preciso consultar o método antigo, está em `HISTORICO.md` (nesta pasta) e no backup
`20261020-164457-pre-troca-sicar-wfs`.
Em 2026-10-21 foi apagada também `catalogo.anomalias_geometria` (2 linhas: o texto original, da carga antiga, dos 2 imóveis anômalos de MA e SE).
Hoje esses imóveis têm `geom_anomala = true` e o texto como o WFS entrega em `geom_origem_texto`, na própria tabela; o original antigo está
nos backups de 20/10 e 21/10 e as coordenadas no `HISTORICO.md`.

Licença: dados abertos do CAR; confirmar os termos antes de redistribuir. **Frequência de atualização: a decidir** (semanal,
quinzenal ou mensal; as 27 UFs levam uns 25 min).
