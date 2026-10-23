# Desmatamento PRODES por imóvel do SICAR — metodologia oficial

Tabela `resultados.desmatamento_imovel`, produzida **só** por `analises/desmatamento_imovel/scripts/desmatamento_imovel.ps1`
(estrutura em `analises/desmatamento_imovel/sql/desmatamento_imovel_estrutura.sql`). Para manter a metodologia, **não refaça a conta à mão**:
rode sempre o script.

## O método

Para cada imóvel **vigente** do SICAR (`vigente_ate IS NULL`, com geometria):

1. Cruza a geometria do imóvel **direto** com todos os polígonos de `vetorial.prodes_desmatamento` que o tocam
   (índice espacial, `ST_Intersects`). **Não** pré-filtra pela ponte `resultados.prodes_municipio`: o município do imóvel é
   atributo do CAR e o da ponte é geométrico; quando divergem (~1,7%), o pré-filtro perde polígonos (medido no MDA:
   106 de 30.039 imóveis, 0,35%).
2. Geometrias inválidas (do imóvel ou do PRODES) são corrigidas na hora com `ST_MakeValid`; nada é gravado corrigido.
3. Soma a **área geodésica** da interseção (`ST_Area(ST_Intersection(...)::geography)`, em m², convertida para ha) por
   **imóvel × ano PRODES × bioma**. Só entra linha com área > 0; imóvel sem desmatamento não tem linha.
4. `pct_area_imovel` = área desmatada ÷ `num_area` do imóvel × 100, **limitado a 999,99** (imóveis de área minúscula).
5. "Ano" é o ano PRODES (`year`). Filtros como "após 2008" (= ano ≥ 2009) são do consumidor, não da tabela.

## Como se liga (importante)

- Junte por **`cod_imovel`**, que é estável entre as versões do SICAR.
- `id_imovel_sicar` guarda a versão **vigente** em que foi calculado (sempre vigente depois de cada execução: "linhas
  apontando para versão fechada" deve ser 0).
- `resultados.desmatamento_imovel_controle` lista as versões de imóvel já processadas, **inclusive as sem desmatamento**, e com
  **quais edições do PRODES** (`edicoes_prodes`, ex.: `amazonia=20261016,...`). O resultado depende das duas fontes: o script
  considera **pendente** a versão vigente do imóvel ainda não processada **ou processada com outra edição do PRODES**
  (`catalogo.v_edicoes_prodes` guarda as edições atuais). Só polígonos **vigentes** do PRODES entram no cruzamento.
- **Use `resultados.v_desmatamento_imovel_vigente`** no dia a dia: só mostra o que ainda vale (versão do imóvel vigente e
  calculada com as edições atuais do PRODES). As tabelas completas ficam para auditoria; não há coluna "vigente" copiada no
  resultado (ela ficaria desatualizada), o status vem do cruzamento com a origem. Resultado de versão fechada continua na tabela
  até a rotina de retenção (`infra/scripts/limpar_versoes_fechadas.py`) apagá-lo junto com a versão, depois do prazo.

## Quando rodar

| Situação | Comando |
|---|---|
| Depois de reconciliar uma UF do SICAR (WFS) | `.\analises\desmatamento_imovel\scripts\desmatamento_imovel.ps1 -UF XX` (só os pendentes: versões vigentes novas) |
| Ensaio, sem gravar | `... -UF XX -Simular` |
| PRODES ganhou edição nova (o pipeline registra a edição) | `... -UF XX` (recalcula só o que ficou com edição antiga) |
| A metodologia mudou | `... -UF XX -Tudo` (recalcula a UF inteira) |
| UF nova, nunca calculada | `... -UF XX` |

Antes de gravar uma UF grande, faça backup com etiqueta (`backup_banco.ps1 -Etiqueta antes-desmat-xx`). Cada lote
(padrão 50.000 imóveis) é uma transação, e a execução é repetível.

## Situação em 2026-10-20 (depois da troca do SICAR pelo WFS)

`vetorial.sicar_imoveis` foi reconstruída do zero pelo WFS do CAR (ids novos; ver `sicar/imoveis/LEIAME_sicar_imoveis.md`).
As tabelas `desmatamento_imovel` e `desmatamento_imovel_controle` foram **apagadas** nessa troca e **estão vazias/inexistentes
até serem recriadas**: rode `desmatamento_imovel.ps1 -UF XX` por UF (o script recria a estrutura sozinho). O script serve na
tabela nova sem mudanças (usa `id`, `cod_imovel`, `cod_estado`, `vigente_ate`, `geom` e `num_area`, que continuam existindo).
Imóveis com `geom_anomala` (geom NULL) ficam de fora, como já ficavam os sem geometria.

## Referências medidas (2026-10-20)

- **Acre:** 57.292 imóveis vigentes processados, 115.764 linhas, 36.103 imóveis com desmatamento, 1.079.830 ha; 1,6 min.
- O piloto antigo do Acre (feito em 01/10, antes da ponte existir) batia com este método **linha a linha** (soma idêntica de
  1.078.473,5 ha sobre as mesmas versões de imóveis). Só ficou defasado pela atualização do SICAR de 16/10.
- Dados do MDA (186 municípios SP/MG) foram apagados do banco em 20/10/2026 a pedido do usuário; a entrega está nos xlsx
  em `projetos/mda/`, com a ressalva do pré-filtro pela ponte em `projetos/mda/LEIAME_proxima_rodada.md`.

## Limitações

- Os imóveis do CAR se sobrepõem entre si: **não some o desmatamento entre imóveis**.
- Só biomas e anos presentes em `prodes_desmatamento`. Imóvel sem geometria (NULL) fica fora e não entra no controle.
- A tabela depende da camada do SICAR: o que o SICAR não tem (cancelados, UFs ainda não carregadas pelo WFS) não tem
  desmatamento calculado.
