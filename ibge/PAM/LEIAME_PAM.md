# ibge/PAM — Produção Agrícola Municipal (IBGE/SIDRA)

Coleta automatizada direto da API do SIDRA, tabela **5457** (lavouras temporárias e permanentes juntas,
1974 em diante, 85 culturas), para `tabular.ibge_pam`. Pipeline: `scripts/pam.py`. Guia geral e como rodar:
`scripts_comuns/LEIAME_pipelines.md`.

**Roda somente sob demanda, por produto.** Não existe carga completa automática: carrega-se uma cultura quando
alguém precisa dela. A carga de todas as culturas exige um pedido explícito (`--confirmar-carga-completa`).

```
ibge/PAM/
├── config.yaml          tabela, variáveis, regras de unidade, validação
├── sql/01_esquema.sql   dim.cultura e tabular.ibge_pam (DDL, por administrador)
├── sql/02_unidade_valor.sql   coluna unidade_valor (para bancos criados antes dela)
├── scripts/pam.py       coleta e carga          
├── bruto/sidra_5457/    pam_<cod>_<ini>-<fim>.jsonl.gz + manifesto (fora do git)
(a coleta manual de erva-mate do RS e o teste de regressão estão em projetos/mate_rs/)
```

## Modelo

- `dim.cultura`: `id_cultura` = **código SIDRA da classificação c782** (soja 40124, erva-mate 40147,
  laranja 40151...). O código 0 (Total) não entra: é a soma dos demais.
- `tabular.ibge_pam`: **uma linha por município x cultura x ano**, com as 5 variáveis em colunas
  (`area_plantada_ha`, `area_colhida_ha`, `quantidade_produzida`, `rendimento_medio`,
  `valor_producao_mil_reais`) e `unidade_quantidade`/`unidade_rendimento`/`unidade_valor`.
  `UNIQUE (id_municipio, id_cultura, ano)`.
- **Só há linha quando alguma variável é > 0.** O SIDRA devolve `-` (zero) para município que não produz a
  cultura: na soja de 2023, metade das células. Ausência de linha = zero ou sem dado. `-` vira 0 e `...` vira NULL
  dentro de uma linha existente.
- **Variáveis percentuais nunca são coletadas** (1008331, 1000216, 1000215: percentual do total geral). Derivam
  do total e se recalculam das colunas acima. Estão listadas em `variaveis_ignoradas` no `config.yaml` e o
  pipeline recusa rodar se alguma aparecer em `variaveis`.
- **Total nacional** = `SUM` sobre os municípios da cultura e ano (a validação do pipeline confere que bate com
  o total nacional da API, tolerância 0,1%).

## Armadilhas da fonte (verificadas em 2026-10-14)

- **A API rotula tudo como "Toneladas" e "Quilogramas por Hectare", em todos os produtos e anos, mas não é
  verdade.** Até 2000, 12 produtos têm a quantidade e o rendimento em outra unidade (mil frutos, mil cachos):
  melancia, banana (cacho), caqui, figo, goiaba, laranja, limão, maçã, maracujá, pera, pêssego, tangerina. A
  evidência é o salto de ordem de grandeza entre 2000 e 2001 nos totais nacionais sem salto na área colhida
  (laranja: 106,7 milhões em 2000, 17,0 milhões em 2001). Os números ficam como o IBGE devolve; `unidade_*` diz a
  unidade. O **nome** da unidade antiga é inferido (o dado prova que mudou, não o nome); pode haver culturas com
  quebra pequena demais para a varredura detectar. Detalhes e a lista: `config.yaml`.
- **O valor da produção até 1993 não está em reais.** A API diz "Mil Reais" em todos os anos, mas a série
  nacional quebra a cada reforma monetária (laranja: razão entre anos vizinhos de 0,00 em 1985, 16,50 em 1988,
  0,03 em 1993, 0,01 em 1994). Até 1993 o valor está na moeda nominal da época e `unidade_valor` diz
  `moeda nominal da epoca (pre-Real; nao comparavel)`; de 1994 em diante é mil reais nominais (sem deflacionar).
  **Não compare nem some valores de anos diferentes sem filtrar `unidade_valor`.**
- **`Abacaxi*` e `Coco-da-baía*`** têm nota de rodapé do IBGE que não conseguimos ler pela API: a unidade fica
  `a confirmar (nota * do IBGE)` em todos os anos, em vez de assumir toneladas.
- **Limite de 50.000 valores por pedido.** Todos os municípios x todos os produtos de um ano são 478 mil; por
  isso o pedido é por cultura x ano (27.820 valores, 1 a 7 s).
- **Municípios:** o PAM usa a lista vigente do IBGE (5.571). A dimensão se mantém com
  `ibge/municipios/scripts/localidades.py` (o `5101837` Boa Esperança do Norte/MT foi acrescentado assim).

## Como rodar (a partir de D:\data_warehouse\infra)

```powershell
# listar as culturas e o que já está carregado
docker compose -f docker-compose.stack.yml -f docker-compose.etl.yml run --rm etl ibge/PAM/scripts/pam.py --listar
# carregar UMA cultura, série inteira (código ou slug); --anos 1990,2000 ou --desde/--ate limitam a janela
... run --rm etl ibge/PAM/scripts/pam.py --culturas laranja
# atualização de rotina: só culturas JÁ carregadas, últimos 3 anos (a PAM anual sai por volta de set/out)
... run --rm etl ibge/PAM/scripts/pam.py --atualizar
# mais rapido: ate 4 pedidos simultaneos ao SIDRA (padrao 1; a gravacao segue em ordem, numa conexao so)
... run --rm etl ibge/PAM/scripts/pam.py --culturas soja_em_grao --paralelo 3
# ensaio sem gravar (uma transação desfeita no fim)
... run --rm etl ibge/PAM/scripts/pam.py --culturas laranja --simular
# teste de regressão contra a coleta manual de erva-mate do RS
... run --rm etl projetos/mate_rs/validar_mate_rs.py
```

Reexecutar é seguro: o upsert só regrava linhas cujo valor mudou.

Resultados de referência (2026-10-14): erva-mate 2023-2025 no RS, 1.482 comparações com a coleta manual,
0 diferenças. Laranja, série nacional 1974-2025: 153.937 linhas, 4.877 municípios; 2024 = 15,7 Mt.
