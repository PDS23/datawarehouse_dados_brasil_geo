# ibge/censo_agropecuario — Censo Agropecuário 2017: estabelecimentos com lavoura permanente

> **Atualizado em 2026-10-23:** a coleta do Censo agora é feita pela **camada genérica do SIDRA** (`../sidra/`, pipeline `scripts/sidra.py --tabela 6956`).
> `tabular.ibge_censoagro2017_estab_lavoura_perm` é hoje uma **visão** sobre `tabular.sidra_valor` (mesmas colunas, sem o `id`). O script, o `config.yaml`, o
> `sql/01_esquema.sql` e as tabelas `dim.produto_censo_lavoura_perm` e `dim.grupo_area_total` descritos abaixo **foram removidos** (as categorias estão em `dim.sidra_categoria`). As seções "Modelo" e "Como rodar" descrevem o desenho
> antigo e valem só como histórico. O universo de tabelas, as armadilhas e a consulta típica continuam válidos. Como rodar agora: `../sidra/LEIAME_sidra.md`.

Coleta automatizada direto da API do SIDRA, tabela **6956** ("lavoura permanente nos estabelecimentos
agropecuários, por tipologia, produtos da lavoura permanente e grupos de área total"), nível município.
Pipeline: `scripts/censo_agropecuario.py`. **Roda somente sob demanda, por produto.**

```
ibge/censo_agropecuario/
├── config.yaml                 tabela, classificações, variáveis, tipologia fixa
├── sql/01_esquema.sql          dim.grupo_area_total, dim.produto_censo_lavoura_perm e a tabela fato (DDL, por administrador)
├── scripts/censo_agropecuario.py  coleta e carga
└── bruto/sidra_6956/           censoagro2017_<produto>.jsonl.gz + manifesto (fora do git)
```

## O universo de tabelas do Censo no SIDRA (levantamento de 2026-10-21, pela API oficial `servicodados.ibge.gov.br/api/v3/agregados`)

O Censo Agropecuário tem **1.407 tabelas** no SIDRA (1.406 com metadados lidos): **735 do Censo 2017** (497 com nível municipal), 554 do 2006
(mais 17 séries históricas 1920-2006) e 100 do 1995/96. A que carregamos (6956) é só **uma fatia de uma tabela**: ela tem 12 variáveis
(contagem de estabelecimentos com 50 pés e mais e com menos de 50, quantidade produzida e vendida, valor da produção e da venda, área colhida e
total, pés existentes e colhidos) e 3 eixos (tipologia × 71 produtos × 20 grupos de área); carregamos 2 variáveis e fixamos a tipologia no Total.

Números que pesam na decisão de modelagem (cada tabela é uma combinação de eixos de quebra + variáveis):
- **1.175 combinações distintas de eixos** para 1.406 tabelas; 1.083 tabelas têm combinação única (a mais repetida aparece em 16): uma tabela
  tipada por tabela do SIDRA significaria centenas de estruturas diferentes.
- Os **eixos se repetem**: só 192 classificações distintas (1.889 categorias no total); as mais usadas são condição do produtor (718 tabelas),
  grupos de área total (565) e grupos de atividade econômica (562). Uma dimensão genérica de categorias cabe em ~2 mil linhas.
- **882 variáveis distintas**, 541 reaproveitadas entre tabelas; em 291 de 6.115 variáveis a **unidade depende da categoria** ("Vide categorias da
  classificação...": toneladas num produto, mil frutos em outro).
- **Tamanho:** nas 497 tabelas de 2017 com município, o teto de células (municípios × categorias, antes de descontar vazias) tem mediana de 59 milhões,
  p90 de 855 milhões e soma de 173 bilhões; só 46 têm até 5 milhões. Carregar o Censo inteiro é inviável: continua **sob demanda, por tabela e por recorte**.

Decisão pendente de modelagem (uma tabela por tabela do SIDRA, uma tabela genérica ou híbrido): ver o registro no diário (entrada 0083).

## Como a tabela do SIDRA funciona

O SIDRA guarda um cubo: cada número é identificado por uma combinação de dimensões. Na 6956:
variável, município, ano (só 2017), **produto** (c227), **grupo de área total** (c220) e **tipologia** (c829).
No banco: município x grupo de área são as **linhas**, as variáveis são as **colunas**, e produto, tipologia
(fixa em Total, `46302`) e ano são **filtros**.

## Modelo

- `dim.grupo_area_total`: as 19 faixas (c220), de "produtor sem área" a "10.000 ha e mais", com `ordem` e
  limites em ha. O "Total" (110085) não entra: é a soma das faixas.
- `dim.produto_censo_lavoura_perm`: 70 produtos (c227; laranja = 4961). **Os códigos não são os da PAM** (`dim.cultura`).
- `tabular.ibge_censoagro2017_estab_lavoura_perm`: uma linha por município x produto x faixa de área, com
  `estab_50_pes_mais` (variável 9504) e `estab_menos_50_pes` (variável 10081). `UNIQUE (id_municipio, id_produto, id_grupo_area)`.
- **Só há linha quando há estabelecimentos (> 0) ou dado em sigilo.** Ausência de linha = zero (`-`) ou não se aplica (`...`).
- **Sigilo (`X`):** o IBGE inibe valores para não identificar o informante. Vira `NULL` com `*_sigilo = true`;
  não é zero, e a soma dos municípios pode ficar abaixo do total nacional por isso.

## Armadilhas

- **A contagem tem duas metades, e não se somam sem pensar.** `estab_50_pes_mais` são os estabelecimentos
  com 50 pés ou mais do produto (os únicos para os quais o censo publica produção); `estab_menos_50_pes` são
  os com menos de 50 pés (quintais, pomares domésticos). Na laranja do Brasil: 55.912 x 573.260. Para
  "propriedades produtoras" em sentido comercial, use a primeira coluna; some as duas só se quiser todos
  que têm algum pé.
- **A faixa é o tamanho do ESTABELECIMENTO (área total), não do pomar.**
- A tabela do SIDRA cobre 5.489 municípios (os que têm lavoura permanente no censo), não os 5.571 da dimensão.
- Tipologia fixa em Total: sem separar agricultura familiar / Pronaf / Pronamp.
- Só estabelecimentos. Quantidade produzida, valor, área e pés existem na 6956 mas não foram pedidos
  (variáveis 9506, 10076, 10078, 10079, 10080...).

## Como rodar (a partir de D:\data_warehouse\infra)

```powershell
# listar os produtos e o que já está carregado
docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl ibge/censo_agropecuario/scripts/censo_agropecuario.py --listar
# carregar um produto (código ou slug); --grupos 111551,111552 limita as faixas (útil para teste)
... run --rm etl ibge/censo_agropecuario/scripts/censo_agropecuario.py --produtos laranja
# ensaio sem gravar
... run --rm etl ibge/censo_agropecuario/scripts/censo_agropecuario.py --produtos laranja --simular
```

Para o produto inteiro a API leva alguns minutos (ela é lenta). Reexecutar é seguro.

## Consulta típica

```sql
-- distribuição das propriedades produtoras de laranja por tamanho, em um município
SELECT g.ordem, g.nome, e.estab_50_pes_mais, e.estab_menos_50_pes
FROM tabular.ibge_censoagro2017_estab_lavoura_perm e
JOIN dim.grupo_area_total g USING (id_grupo_area)
WHERE e.id_produto = 4961 AND e.id_municipio = 3506003   -- Bebedouro/SP
ORDER BY g.ordem;
```
