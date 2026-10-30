# ibge/pedologia — Pedologia (Banco de Informações Ambientais do IBGE)

Espelho versionado, em `vetorial.ibge_pedologia`, do tema **Pedologia** do **BDiA** (Banco de Informações Ambientais) do IBGE, escala 1:250.000, direto do servidor de arquivos do IBGE
([`pedologia/vetores/escala_250_mil/`](https://geoftp.ibge.gov.br/informacoes_ambientais/pedologia/vetores/escala_250_mil/)). Mapa de solos do Brasil (pedologia) do BDiA, 1:250.000: associações de solos por polígono.
**114.658 feições** na edição **2026** (a mais recente publicada). Mesma mecânica das outras fontes vivas (regras em `scripts_comuns/dwlib/espelho.py`): feição nova entra; alterada fecha a versão antiga e
insere a nova; a que a edição nova não traz tem a versão **fechada** (nada é apagado); a que sumiu e voltou **idêntica** tem a versão **reaberta**. Vigente = `vigente_ate IS NULL`.

```
ibge/pedologia/
├── LEIAME_pedologia.md · HISTORICO.md
├── config.yaml                          URL, colunas e tipos, limites de sanidade
├── sql/01_tabela.sql                    tabela, índices, mapa de colunas e permissões (rodar como postgres)
└── scripts/pedologia.py                   chama scripts_comuns/dwlib/bdia.py (a mecânica é comum aos 4 temas do BDiA)
```

```powershell
.\infra\scripts\dw.ps1 etl ibge/pedologia/scripts/pedologia.py --verificar   # quais edições o IBGE tem e qual o banco tem
.\infra\scripts\dw.ps1 etl ibge/pedologia/scripts/pedologia.py --simular     # ensaio, nada gravado
.\infra\scripts\dw.ps1 etl ibge/pedologia/scripts/pedologia.py               # baixa (pedo_area.zip, ~400 MB) e reconcilia (~1 a 2 min)
```

100% automático: o pipeline lê a listagem do diretório do IBGE, escolhe a pasta `versao_AAAA` mais recente, baixa o zip, confere o tamanho, descompacta numa área temporária e lê o shapefile em
lotes de 10 mil feições (o `.shp` passa de 1 GB). Confere os campos esperados e aborta se o zip vier truncado ou com poucas feições. `--edicao AAAA` carrega outra edição (o IBGE tem 2017, 2018, 2019,
2021, 2023, 2025 e 2026); a última carregada vira a vigente. O zip **não é guardado** (é baixado de novo a cada carga).

## O que a fonte tem de particular

- **A chave é `id1`**, o id da feição no shapefile (único em cada edição; confirmado). Se o IBGE renumerar o `id1` numa edição nova, o espelho vai mostrar a edição inteira como troca (feições antigas
  fechadas, novas abertas) e a trava de queda de 10% impede que isso entre sem `--aceitar-queda`.
- **Os campos que o IBGE grava como decimal mas são códigos inteiros** (`id_unidade`, `cd_*_id` etc.) viram `integer`; `ar_poli_km` (área do polígono em km², do IBGE) vira `numeric`. O resto é texto,
  como a fonte publica (vazio e `None` viram `NULL`).
- **A unidade é uma associação de solos**: `componente`, `component1` a `component3` e `inclu_p1` a `inclu_p3` listam os solos que ocorrem juntos no polígono. `horizonte` pode ter quebra de linha dentro do texto. **43.978 feições (38%) não têm solo**: 40.188 são corpos d'água continentais e 3.790 áreas urbanas (`cod_simbol`, `ordem` e `componente` ficam vazios; `legenda` diz o que são).
- **89 polígonos são inválidos pelo PostGIS** e entram como vêm (use `ST_MakeValid` na análise). Vira tudo MultiPolygon em SIRGAS 2000 (4674). Tabela grande: filtre por atributo ou por área antes de cruzar.
- É a camada de **polígonos** (`*_area`). O IBGE publica nas mesmas pastas camadas de linhas, pontos, tabelas e a simbologia, que **não são carregadas**.
- Os domínios e regiões naturais (`ibge_dominios_naturais`, `ibge_regioes_naturais`) são outra fonte do IBGE e não vêm deste pipeline.

## Licença

Dados abertos do IBGE; confirmar os termos de uso e a citação exigida antes de redistribuir.
