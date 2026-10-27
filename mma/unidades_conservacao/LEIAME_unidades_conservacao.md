# mma/unidades_conservacao — Unidades de conservação (CNUC, Ministério do Meio Ambiente)

Espelho versionado, em `vetorial.mma_unidades_conservacao`, do **Cadastro Nacional de Unidades de Conservação (CNUC)**, publicado no portal de dados abertos do MMA
([dataset](https://dados.mma.gov.br/dataset/44b6dc8a-dc82-4a84-8d95-1b0da7c85dac)). Edição carregada: **2026_07** (21/08/2026), 3.576 UCs: 3.406 com polígono e 170 só com ponto esquemático.
Mesma mecânica das outras fontes vivas (regras em `scripts_comuns/dwlib/espelho.py`): UC nova entra; alterada fecha a versão antiga e insere a nova; UC que a edição nova
não traz tem a versão **fechada** (nada é apagado); UC que sumiu e voltou **idêntica** tem a versão **reaberta**. Vigente = `vigente_ate IS NULL`.

## Esta fonte é uma CARGA MANUAL AUTORIZADA

O projeto só carrega dado por pipeline que baixa direto da fonte (regra 8). **Esta é a exceção**, autorizada pelo usuário em 2026-10-27: o MMA publica o shapefile do CNUC mais
recente (2026_03 e 2026_07) apenas em links do **SharePoint** (com token, instáveis), que não se baixam por script; o CKAN só traz o shapefile até 2025_08. Como o dado
atualizado importa mais que a automação total, o usuário baixa o zip e o coloca em `bruto/`.

```
mma/unidades_conservacao/
├── LEIAME_unidades_conservacao.md · HISTORICO.md
├── config.yaml                          CKAN, campos esperados, limites de sanidade, caixa do Brasil
├── sql/01_tabela.sql                    fonte em dim.fontes, tabela, índices, mapa de colunas e permissões (rodar como postgres)
├── scripts/unidades_conservacao.py      lê o zip de bruto/ e reconcilia (usa dwlib/espelho.py); --verificar consulta o CKAN
└── bruto/cnuc_AAAA_MM.zip               zip baixado à mão (fora do git e do Drive); o SHA-256 fica em catalogo.coletas
```

**Para atualizar** (quando o MMA publicar uma edição nova): baixe o zip (SharePoint da página do dataset), coloque em `bruto/` **sem alterar nada** (o nome `cnuc_AAAA_MM.zip` dá a edição) e rode:

```powershell
.\infra\scripts\dw.ps1 etl mma/unidades_conservacao/scripts/unidades_conservacao.py --verificar   # o CKAN ja tem link direto? qual edicao o banco tem?
.\infra\scripts\dw.ps1 etl mma/unidades_conservacao/scripts/unidades_conservacao.py --simular     # ensaio, nada gravado
.\infra\scripts\dw.ps1 etl mma/unidades_conservacao/scripts/unidades_conservacao.py               # reconcilia a edicao mais recente de bruto/
```

`--verificar` lista os recursos do CKAN e diz se o MMA passou a publicar a edição nova num link direto. Quando isso acontecer, a coleta pode virar automática e esta exceção cai.
Fica **fora** da atualização agendada (`atualizar_fontes.ps1`): sem o zip novo em `bruto/` não há o que atualizar.

## O que o zip traz

Dois shapefiles em SIRGAS 2000 (EPSG:4674) com UCs **diferentes** (nenhuma se repete):

- **Polígonos** (`cnuc_26_07_31.shp`, 3.406 UCs): limite da UC, com os campos completos (atos, plano de manejo, conselho gestor, área por bioma...). 0 geometrias inválidas, nenhuma fora do Brasil;
  mistura Polygon e MultiPolygon (tudo vira MultiPolygon).
- **Pontos** (`cnuc_2026_07_pontos.shp`, 170 UCs): UCs que **não têm polígono** nesta edição; o ponto é só uma representação esquemática. Têm campos próprios (`NomeAbrev`, mosaico, sítio Ramsar...).

Uma tabela só: `geom` (polígono) para as 3.406, `geom_ponto` (derivado de `longitude_ponto` e `latitude_ponto`) para as 170, e `camada_origem` diz de qual shapefile veio. A chave é `cd_cnuc`
(única em cada shapefile e sem repetição entre eles).

## Particularidades

- **Tudo vem como texto no shapefile** (áreas, datas, até contagens): o pipeline converte as áreas em hectares para `numeric`. `cria_ano` vem `dd-mm-aaaa` nos polígonos e só o ano nos pontos; guardamos como vem e
  derivamos `ano_criacao`.
- **`uf` e `municipio` são listas** em texto (`ALAGOAS, BAHIA, SERGIPE`; `AIURUOCA (MG), ALAGOA (MG)`): UCs que cruzam UFs ou municípios não têm um `id_estado`/`id_municipio` único; para ligar a UC à
  malha use a geometria.
- **`esfera` muda de capitalização** (`Federal` nos polígonos, `federal` em parte dos pontos); `grupo` vem por extenso nos polígonos e como `PI`/`US` nos pontos. Compare com `lower()`.
- `quali_pol` diz a qualidade do limite: 2.566 polígonos correspondem ao memorial descritivo, 724 são estimativa dos limites e 115 são representação esquemática.
- O esquema é conferido: se o MMA mudar os campos do shapefile, nada é gravado.
- A edição vem do nome do zip e fica em `edicao` na versão em que cada UC entrou; trocar de edição sem mudar uma UC não cria versão nova.

## Licença

Dados abertos do MMA; confirmar os termos de uso e a citação exigida antes de redistribuir.
