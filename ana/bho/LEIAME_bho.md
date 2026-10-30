# ana/bho — Base Hidrográfica Ottocodificada 1:250.000 (BHO250, ANA)

Espelho versionado, em quatro tabelas de `vetorial`, da **Base Hidrográfica Ottocodificada 1:250.000 (BHO250)** da Agência Nacional de Águas e Saneamento Básico (ANA), publicada no catálogo de
metadados do SNIRH ([registro](https://metadados.snirh.gov.br/geonetwork/srv/eng/catalog.search#/metadata/0f57c8a0-6a0f-4283-8ce3-114ba904b9fe)). Versão **02_03** (dez/2023). A "ottocodificação"
(método de Otto Pfafstetter) dá a cada trecho de rio e a cada bacia um código que diz o que está a montante e a jusante.
Mesma mecânica das outras fontes vivas (regras em `scripts_comuns/dwlib/espelho.py`): feição nova entra; alterada fecha a versão antiga e insere a nova; a que a versão nova não traz tem a versão
**fechada** (nada é apagado); a que sumiu e voltou **idêntica** tem a versão **reaberta**. Vigente = `vigente_ate IS NULL`.

| Tabela | O que é | Feições | Chave |
|---|---|---|---|
| `vetorial.ana_bho_trechos_drenagem` | rede de rios em linhas, um trecho por feição | 1.614.231 | `cotrecho` (+ ordinal) |
| `vetorial.ana_bho_cursos_dagua` | cada rio inteiro como uma linha (vários trechos) | 807.103 | `idcda` (+ ordinal) |
| `vetorial.ana_bho_linha_costa` | linha de costa | 25 | `colinhacosta` (+ ordinal) |
| `vetorial.ana_bho_bacias_otto` | bacias hidrográficas ottocodificadas, níveis 1 a 6 numa tabela só | 23.608 | nível + `wts_pk` |

```
ana/bho/
├── LEIAME_bho.md · HISTORICO.md
├── config.yaml                          registro do catálogo, camadas, colunas e tipos, limites de sanidade
├── sql/01_tabelas.sql                   as 4 tabelas, índices, mapa de colunas e permissões (rodar como postgres)
└── scripts/bho.py                       lê o catálogo da ANA, baixa o GeoPackage de cada camada e reconcilia (usa dwlib/espelho.py)
```

```powershell
.\infra\scripts\dw.ps1 etl ana/bho/scripts/bho.py --verificar                       # versão do catálogo da ANA x o que o banco tem
.\infra\scripts\dw.ps1 etl ana/bho/scripts/bho.py --simular --camadas linha_costa   # ensaio de uma camada, nada gravado
.\infra\scripts\dw.ps1 etl ana/bho/scripts/bho.py                                   # as 4 camadas (~2,6 GB de download); --camadas escolhe quais
```

100% automático: links diretos do catálogo da ANA, sem login; a versão vem do nome do arquivo da base completa (`bho_250k_v_02_03.gpkg`). O pipeline lê cada GeoPackage em lotes de 50 mil feições,
confere os campos, o tamanho do arquivo e o número mínimo de feições, e **aborta sem gravar** se algo não bater. Cada camada roda em transação própria.

## Escolhas de volume (o que NÃO foi carregado)

- **A BHO 2017, que o ROADMAP citava, está marcada pela ANA como "Desatualizada"**; as versões atuais são a **BHO multiescalas 6** (mais de 40 GB: só as áreas de contribuição têm 20 GB) e a **BHO 250**
  (1:250.000, a carregada aqui). Escolhemos a 1:250.000, na mesma escala do BDiA do IBGE e do resto do banco.
- Da BHO 250 **não foram carregadas** as **áreas de contribuição** (1,6 milhão de polígonos, 3,7 GB) nem os **pontos de drenagem** (1,6 milhão de pontos, 284 MB): se uma análise precisar da ottobacia de
  cada trecho, carrega-se sob demanda (mesmo pipeline, nova camada no `config.yaml`). A base completa (`bho_250k_v_02_03.gpkg`, 5,9 GB) também não é carregada.
- Para análises que precisam de mais detalhe (1:50.000 ou 1:5.000), a BHO multiescalas 6 existe, mas custaria dezenas de GB no banco: decisão a tomar quando houver demanda.

## O que a fonte tem de particular

- **A rede é codificada:** `cobacia` (ottobacia do trecho) e `cocursodag` (curso d'água) são códigos de Pfafstetter; `nunivotto` e `nunivotcda` dizem o nível de codificação; `nustrahler` é a ordem de Strahler.
  `nucomptrec`, `nuareacont` e as demais medidas numéricas vêm em km e km², como a ANA publica.
- **Nomes dos rios** (`nogenerico`, `noespecif`, `noriocomp`, `nooriginal`) estão vazios na maior parte dos trechos: a base cartográfica 1:250.000 só nomeia os rios maiores.
- **`dedominial`** diz a dominialidade do curso d'água (federal ou estadual).
- **Chaves repetidas na própria fonte:** 31 trechos repetem o `cotrecho`, 15 cursos repetem o `idcda` e os 25 segmentos da linha de costa têm todos o código `1`. A chave (`chave_linha`) é o campo da chave com ordinal (`#2`...) nas repetições, na ordem do arquivo.
- **Bacias Otto:** os seis níveis do arquivo (`geoft_bho_ach_otto_nivel_01` a `06`) viram uma tabela só; o `wts_pk` só é único dentro do nível, por isso a chave é nível + `wts_pk`. Um polígono por nível não tem código de bacia (`wts_cd_pfafstetterbasin` vazio).
- **A BHO vai além do Brasil:** inclui os rios das bacias transfronteiriças (Peru, Colômbia, Paraguai, Uruguai...), então as geometrias passam do retângulo do Brasil; a caixa de conferência é a da América do Sul. (Na primeira carga a caixa era a do Brasil e 13.452 trechos, 6.790 cursos e 293 bacias foram marcados como anômalos; a recarga restaurou todos.)
- **Tabelas grandes** (1,6 e 0,8 milhão de linhas): filtre por bacia, estado ou caixa antes de cruzar; `ST_DWithin` com `geography` para distâncias em metros (rios dentro de X m de um imóvel).
- Nenhuma geometria é inválida pelo PostGIS. Tudo em SIRGAS 2000 (4674), MultiLineString ou MultiPolygon.

## Licença

Dados abertos da ANA (SNIRH); confirmar os termos de uso e a citação exigida antes de redistribuir.
