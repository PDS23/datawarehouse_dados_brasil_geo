# funai/terras_indigenas — Terras indígenas (FUNAI)

Espelho versionado, em `vetorial.funai_terras_indigenas`, da camada `Funai:tis_poligonais` do servidor de mapas da FUNAI (WFS aberto, sem login):
665 terras indígenas (Brasil inteiro), 117 milhões de hectares. Mesma mecânica do SICAR, do PRODES e do MapBiomas Alerta: terra nova entra; alterada
fecha a versão antiga e insere a nova; terra que o servidor deixou de publicar tem a versão **fechada** (nada é apagado na coleta); terra que sumiu e
voltou **idêntica** tem a versão **reaberta**. Vigente = `vigente_ate IS NULL`. A FUNAI diz atualizar a camada mensalmente; entra na atualização
periódica (`infra/scripts/atualizar_fontes.ps1`).

```
funai/terras_indigenas/
├── LEIAME_terras_indigenas.md · HISTORICO.md
├── config.yaml                       servidor, camada, count, tolerâncias
├── sql/01_tabela.sql                 fonte em dim.fontes, tabela, índices, mapa de colunas e permissões (rodar como postgres)
├── scripts/terras_indigenas.py       baixa a camada inteira e reconcilia (usa dwlib/espelho.py)
└── bruto/wfs/tis_poligonais.jsonl.gz a camada em GeoJSON, uma feição por linha (fora do git e do Drive)
```

```powershell
.\infra\scripts\dw.ps1 etl funai/terras_indigenas/scripts/terras_indigenas.py --simular    # ensaio, nada gravado
.\infra\scripts\dw.ps1 etl funai/terras_indigenas/scripts/terras_indigenas.py              # baixa e reconcilia
```

## Como baixamos (particularidades do servidor)

- **`count` é obrigatório.** Um `GetFeature` sem `count` leva `403 Forbidden` de um filtro nginx na frente do GeoServer (com `count=1` ou `count=10000`
  responde normalmente; `resultType=hits` e SHAPE-ZIP também foram barrados nos testes). O pipeline pede `count=10000` (a camada tem 665 feições, 49 MB).
- **Certificado incompleto.** O servidor envia só o certificado do site, sem a intermediária (Sectigo OV R36): o Python recusa (`unable to get local issuer
  certificate`), embora o navegador e o Windows busquem a intermediária sozinhos. `scripts_comuns/dwlib/certs/sectigo_ov_r36.pem` traz essa
  intermediária **pública** e a verificação do certificado continua ligada (`http.sessao(ca_extra=...)`). Se a FUNAI trocar de autoridade
  certificadora, a coleta falha com o mesmo erro e é preciso acrescentar a nova intermediária.
- **Precisão:** o GeoJSON do servidor (`srsName=EPSG:4674`) traz as coordenadas com 8 casas decimais, sem o corte em 4 casas que vimos no MapBiomas.
  Todas as geometrias são `MultiPolygon`; nenhuma ficou anômala na primeira carga.
- A camada vem em **SIRGAS 2000** (EPSG:4674), o mesmo CRS do banco: nada é reprojetado.

## Colunas

Nomes da fonte (mapa em `catalogo.mapa_colunas`). `terrai_codigo` é a chave estável (665 distintos, nenhum repetido). `fase_ti` traz a fase do processo
de regularização (Regularizada 494, Declarada 73, Delimitada 45, Encaminhada RI 28, Homologada 17, Em Estudo 8). `data_atualizacao` vem como
`dd/mm/aaaa` e vira `date`; `dominio_uniao` vem como `t`/`f` e vira `boolean`. **`id_estado` só é preenchido quando a terra está numa UF única**: 18 terras
atravessam mais de uma UF (`uf_sigla` = `AM,PA`, `MT,PA`...) e ficam com `id_estado` NULL; use `uf_sigla` ou a geometria para essas.

## Outras camadas do mesmo servidor (não carregadas)

`tis_poligonais_portarias` (as mesmas 665 terras com a **data e o título do ato de cada fase**: Portaria, Despacho, Decreto — útil para saber *quando*
cada terra foi declarada, homologada e regularizada), `tis_amazonia_legal_poligonais`, `tis_pontos` e `tis_pontos_portarias` (terras em estudo, pontos),
`aldeias_pontos`, `tis_cr` e `tis_ctl` (coordenações). Candidata a uma segunda tabela se a análise pedir o histórico dos atos.

## Licença

Dados abertos da FUNAI; confirmar os termos de uso e a citação exigida antes de redistribuir.
