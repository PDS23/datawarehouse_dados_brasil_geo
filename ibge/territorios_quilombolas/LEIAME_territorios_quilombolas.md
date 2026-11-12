# ibge/territorios_quilombolas — territórios quilombolas oficialmente delimitados (IBGE)

Espelho versionado, em `vetorial.ibge_territorios_quilombolas`, dos **territórios quilombolas oficialmente delimitados** em polígono, publicados pelo IBGE no servidor de mapas (`geoservicos.ibge.gov.br`,
workspace `CGMAT`). A camada atual é `qg_2022_620_territorioquilombola__v02` (edição 2022, versão 2): **495 territórios em 25 UFs**.
Mesma mecânica das outras fontes vivas (regras em `scripts_comuns/dwlib/espelho.py`): território novo entra; alterado fecha a versão antiga e insere a nova; o que a coleta não traz tem a versão **fechada**
(nada é apagado); o que sumiu e voltou **idêntico** tem a versão **reaberta**. Vigente = `vigente_ate IS NULL`. Chave: `cd_recorte`.

```
ibge/territorios_quilombolas/
├── LEIAME_territorios_quilombolas.md · HISTORICO.md
├── config.yaml                                   endereço do WFS, padrão do nome da camada, limites de sanidade
├── sql/01_tabela.sql                             a tabela, índices, mapa de colunas e permissões (rodar como postgres)
├── scripts/territorios_quilombolas.py            descobre a camada mais recente, baixa e reconcilia (usa dwlib/espelho.py)
└── bruto/wfs/                                    GeoJSON da última coleta (fora do git)
```

```powershell
.\infra\scripts\dw.ps1 etl ibge/territorios_quilombolas/scripts/territorios_quilombolas.py --verificar   # camada que o IBGE publica hoje x a que o banco tem
.\infra\scripts\dw.ps1 etl ibge/territorios_quilombolas/scripts/territorios_quilombolas.py --simular     # ensaio, nada gravado
.\infra\scripts\dw.ps1 etl ibge/territorios_quilombolas/scripts/territorios_quilombolas.py               # carga (segundos)
```

100% automático, sem login: o pipeline lê o `GetCapabilities` do workspace e usa a camada `qg_AAAA_620_territorioquilombola__vNN` de **maior ano e versão**; quando o IBGE publicar uma edição nova, ela
entra sozinha (o ano e a versão ficam em `camada_origem`). Ele confere o total anunciado, o mínimo de 400 territórios e a caixa do Brasil, e **aborta sem gravar** se algo não bater.

## O que esta base é, e o que não é

- **Não é a base do INCRA.** O INCRA é o órgão que titula territórios quilombolas; o IBGE publica a camada a partir da base do INCRA "sempre que possível" e lista só os **oficialmente delimitados**. A data
  é a da edição do IBGE (2022): territórios titulados ou delimitados depois não aparecem até o IBGE publicar uma edição nova.
- **Existe porque o acervo fundiário do INCRA está fora do ar** (manutenção do código PHP, sem previsão; INCRA e SERPRO confirmaram que o serviço volta). É o **escape** para o critério 12 da pré-análise de
  legalidade EUDR (sem sobreposição com território quilombola). Quando o INCRA voltar, ele entra como fonte própria (`incra/`), em tabela própria, e esta continua como histórico: uma fonte por tabela.
- **O MapBiomas não serve de alternativa:** não distribui limites de territórios quilombolas (só estatísticas por território, calculadas sobre limites do INCRA ou do IBGE); conferido em 12/11/2026.
- **Só polígono.** Comunidades quilombolas em ponto (localidades, Censo 2022) são outra camada do IBGE e não estão aqui.

## O que a fonte tem de particular

- Campos: `cd_recorte` (quadro 620 + `cd_tq`, a chave), `cd_tq`, `nm_tq`, `status`, `quadro`, `cd_uf`, `sg_uf`. `status` diz a fase do processo: `TITULADO` (147), `RTID` (138), `DECRETO` (82), `PORTARIA` (72),
  `ESTUDO TÉCNICO` (40), `DELIMITADO` (16). **Atenção para a análise:** só `TITULADO` e `DECRETO` são território com direito já reconhecido; as outras fases são processo em andamento. Decisão de qual fase conta
  como impedimento é da metodologia (ROADMAP 16.3), não desta tabela.
- A geometria vem com dimensão Z; o pipeline guarda em 2D (`ST_Force2D`) como MultiPolygon, SIRGAS 2000 (4674). Nenhuma geometria é inválida pelo PostGIS e nenhuma ficou fora da caixa do Brasil.
- Soma das áreas: cerca de 3,8 milhões de hectares (somando polígonos que possam se sobrepor).
- Sem dado pessoal: os atributos são só nome do território, fase e UF.

## Licença

Dados abertos do IBGE; confirmar os termos de uso e a citação exigida antes de redistribuir.
