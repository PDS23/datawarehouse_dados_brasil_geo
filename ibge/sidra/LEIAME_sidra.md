# ibge/sidra — SIDRA (IBGE): camada genérica de valores

Um pipeline e uma tabela de valores para **qualquer tabela do SIDRA** (Censo Agropecuário, PAM, LSPA e as próximas pesquisas), em vez de uma
tabela tipada por tabela. Desenho aprovado em 2026-10-21 (ROADMAP, item 12). **Roda somente sob demanda**: uma tabela, as categorias que alguém
pediu, os períodos pedidos (o Censo Agropecuário tem 1.407 tabelas e até bilhões de células: carregar tudo é inviável e inútil).

```
ibge/sidra/
├── LEIAME_sidra.md · HISTORICO.md
├── config.yaml                           uma entrada por tabela do SIDRA (classificações, variáveis, períodos, regras)
├── sql/01_camada_generica.sql            dimensões, tabular.sidra_valor (particionada), função de partição, permissões
├── sql/02_visao_censo_lavoura_permanente.sql   visão tipada do Censo (mesmas colunas da tabela antiga)
├── scripts/sidra.py                      coleta, grava dimensões, reconcilia versões
└── bruto/sidra_<tabela>/                 recortes baixados (jsonl.gz + manifesto), fora do git e do Drive
```

## Modelo (ids em vez de texto)

| Tabela | O que guarda |
|---|---|
| `tabular.sidra_valor` | um valor por célula do cubo; **uma partição por tabela do SIDRA**; `id_cat1..id_cat6` = categorias das classificações da tabela |
| `dim.sidra_tabela` / `dim.sidra_pesquisa` | tabelas já coletadas (id = número oficial) e a pesquisa a que pertencem |
| `dim.sidra_tabela_eixo` | diz que classificação cada `id_catN` representa em cada tabela |
| `dim.sidra_classificacao` / `dim.sidra_categoria` | eixos de cruzamento (produto, grupo de área, tipologia…) e suas categorias (id nosso; faixas com limites em ha) |
| `dim.sidra_variavel` / `dim.unidade` | variáveis (id = código SIDRA) e unidades (id = código MC do SIDRA) |
| `dim.sidra_situacao` | símbolos que o SIDRA usa no lugar de número: `-` zero, `X` sigilo, `...` não se aplica, `..` não disponível |
| `dim.cultura` / `dim.cultura_equivalencia` | cultura canônica e a ligação de cada categoria de produto do SIDRA (PAM c782, Censo c227) a ela, para juntar PAM e Censo |
| `catalogo.sidra_recorte` | o que exatamente foi carregado, quando e por qual carga |

Local: nível 6 = município (`id_municipio`), 3 = UF (`id_estado`), 1 = Brasil. **Só há linha quando o IBGE informou um número ou sigilo**
(`-` e `...` não geram linha, salvo tabela com `guardar_simbolos: true`); sigilo (`X`) vira `valor` NULL com `id_situacao = 2`: não é zero.

**Versões:** espelho versionado, como SICAR, PRODES e MapBiomas. Vigente = `vigente_ate IS NULL`. Valor novo entra; valor que o IBGE revisou fecha a
versão antiga e insere a nova; valor que sumiu do recorte tem a versão fechada; valor que volta idêntico à última versão fechada é **reaberto**
(`reaberto_em`). Trava: se mais de 10% dos valores vigentes do recorte sumirem, não grava (`--aceitar-queda`). Retenção das versões fechadas:
`infra/retencao.yaml`.

A partição de cada tabela é criada pela função `catalogo.sidra_garantir_particao`, que roda com os direitos do administrador: o papel `etl` continua
sem DDL.

## Cultura canônica (juntar PAM e Censo)

A PAM (c782) e o Censo (c227) usam códigos diferentes para a mesma cultura (laranja: 40151 na PAM, 4961 no Censo). `dim.cultura_equivalencia` liga cada
categoria a uma cultura canônica de `dim.cultura` (`sql/03_cultura_equivalencia.sql`): 85 categorias da PAM e 61 das 70 do Censo (39 com cultura da PAM, 22
culturas só do Censo com ids novos a partir de 900001; mudas e "Outros produtos" ficam sem cultura). **Decisão de 2026-10-23:** onde a PAM tem a cultura, o
id canônico é o próprio código c782, então `tabular.ibge_pam` não mudou e consultas antigas seguem valendo. A view do Censo traz `id_cultura`:

```sql
SELECT c.nome, e.id_cultura, sum(e.estab_50_pes_mais) estab, sum(p.area_colhida_ha) area_colhida_ha
FROM tabular.ibge_censoagro2017_estab_lavoura_perm e
JOIN dim.cultura c USING (id_cultura)
JOIN tabular.ibge_pam p ON p.id_cultura = e.id_cultura AND p.id_municipio = e.id_municipio AND p.ano = 2017
GROUP BY 1, 2;
```

## Como rodar

```powershell
# categorias da classificação "pedido" (produtos, no Censo) e o que já está carregado
.\infra\scripts\dw.ps1 etl ibge/sidra/scripts/sidra.py --tabela 6956 --listar
# ensaio, nada gravado
.\infra\scripts\dw.ps1 etl ibge/sidra/scripts/sidra.py --tabela 6956 --cat "227=laranja" --simular
# carga (código ou slug; ENTRE ASPAS, o PowerShell separa vírgulas)
.\infra\scripts\dw.ps1 etl ibge/sidra/scripts/sidra.py --tabela 6956 --cat "227=4961,111647"
```

Cada carga confere a soma dos municípios com o total do Brasil em cada célula e avisa se houver diferença que o sigilo não explique.

## Acrescentar uma tabela do SIDRA

Só edite `config.yaml` (sem SQL novo): número da tabela, pesquisa, períodos, variáveis e a lista de classificações na ordem que virará
`id_cat1`, `id_cat2`… (`pedido`, `todas` ou `fixa`; ver o cabeçalho do arquivo). Nomes, categorias, unidades e variáveis são lidos da própria API.
Se a tabela precisar de mais de 6 classificações ou de um nível além de Brasil/UF/município, o desenho muda (ver ROADMAP).

## Tabelas em uso

| Tabela SIDRA | Conteúdo | Estado |
|---|---|---|
| 6956 | Censo Agropecuário 2017: estabelecimentos com lavoura permanente (municípios) | em uso: `tabular.ibge_censoagro2017_estab_lavoura_perm` é a visão tipada (sql/02); ver HISTORICO.md |

Detalhes do Censo (universo de 1.407 tabelas, armadilhas): `../censo_agropecuario/LEIAME_censo_agropecuario.md`.
