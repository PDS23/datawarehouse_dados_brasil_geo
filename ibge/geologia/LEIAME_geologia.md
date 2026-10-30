# ibge/geologia — Geologia (Banco de Informações Ambientais do IBGE)

Espelho versionado, em `vetorial.ibge_geologia`, do tema **Geologia** do **BDiA** (Banco de Informações Ambientais) do IBGE, escala 1:250.000, direto do servidor de arquivos do IBGE
([`geologia/levantamento_geologico/vetores/escala_250_mil/`](https://geoftp.ibge.gov.br/informacoes_ambientais/geologia/levantamento_geologico/vetores/escala_250_mil/)). Mapa geológico do Brasil (litoestratigrafia) do BDiA, 1:250.000: uma feição por unidade geológica mapeada.
**131.547 feições** na edição **2026** (a mais recente publicada). Mesma mecânica das outras fontes vivas (regras em `scripts_comuns/dwlib/espelho.py`): feição nova entra; alterada fecha a versão antiga e
insere a nova; a que a edição nova não traz tem a versão **fechada** (nada é apagado); a que sumiu e voltou **idêntica** tem a versão **reaberta**. Vigente = `vigente_ate IS NULL`.

```
ibge/geologia/
├── LEIAME_geologia.md · HISTORICO.md
├── config.yaml                          URL, colunas e tipos, limites de sanidade
├── sql/01_tabela.sql                    tabela, índices, mapa de colunas e permissões (rodar como postgres)
└── scripts/geologia.py                   chama scripts_comuns/dwlib/bdia.py (a mecânica é comum aos 4 temas do BDiA)
```

```powershell
.\infra\scripts\dw.ps1 etl ibge/geologia/scripts/geologia.py --verificar   # quais edições o IBGE tem e qual o banco tem
.\infra\scripts\dw.ps1 etl ibge/geologia/scripts/geologia.py --simular     # ensaio, nada gravado
.\infra\scripts\dw.ps1 etl ibge/geologia/scripts/geologia.py               # baixa (geol_area.zip, ~400 MB) e reconcilia (~1 a 2 min)
```

100% automático: o pipeline lê a listagem do diretório do IBGE, escolhe a pasta `versao_AAAA` mais recente, baixa o zip, confere o tamanho, descompacta numa área temporária e lê o shapefile em
lotes de 10 mil feições (o `.shp` passa de 1 GB). Confere os campos esperados e aborta se o zip vier truncado ou com poucas feições. `--edicao AAAA` carrega outra edição (o IBGE tem 2017, 2018, 2019,
2021, 2023, 2025 e 2026); a última carregada vira a vigente. O zip **não é guardado** (é baixado de novo a cada carga).

## O que a fonte tem de particular

- **A chave é `id1`**, o id da feição no shapefile (único em cada edição; confirmado). Se o IBGE renumerar o `id1` numa edição nova, o espelho vai mostrar a edição inteira como troca (feições antigas
  fechadas, novas abertas) e a trava de queda de 10% impede que isso entre sem `--aceitar-queda`.
- **Os campos que o IBGE grava como decimal mas são códigos inteiros** (`id_unidade`, `cd_*_id` etc.) viram `integer`; `ar_poli_km` (área do polígono em km², do IBGE) vira `numeric`. O resto é texto,
  como a fonte publica (vazio e `None` viram `NULL`).
- **Várias colunas de nome por litotipo** (`nm_lito1` a `nm_lito4`): a maioria das unidades tem só o primeiro; os demais ficam vazios. `ordem`, `letra_simb`, `nm_tp_roc` e `nm_stp_roc` vêm vazios nas feições sem unidade litoestratigráfica (corpos d'água, por exemplo).
- **11 polígonos são inválidos pelo PostGIS** e entram como vêm (use `ST_MakeValid` na análise). Vira tudo MultiPolygon em SIRGAS 2000 (4674). Tabela grande: filtre por atributo ou por área antes de cruzar.
- É a camada de **polígonos** (`*_area`). O IBGE publica nas mesmas pastas camadas de linhas, pontos, tabelas e a simbologia, que **não são carregadas**.
- Os domínios e regiões naturais (`ibge_dominios_naturais`, `ibge_regioes_naturais`) são outra fonte do IBGE e não vêm deste pipeline.

## Licença

Dados abertos do IBGE; confirmar os termos de uso e a citação exigida antes de redistribuir.
