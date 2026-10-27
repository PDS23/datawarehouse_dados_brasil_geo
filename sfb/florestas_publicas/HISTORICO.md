# sfb/florestas_publicas — histórico

- **2026-10-23** — levantamento de fontes: o CKAN do SFB tem o CNFP por ano; os CSV não trazem geometria, mas cada ano aponta para um item público do portal ArcGIS (shapefile ZIP).
- **2026-10-27** — pipeline criado (`scripts/florestas_publicas.py`) e primeira carga da edição 2025: 12.874 polígonos (zip de 229,5 MB, baixado em 48 s, SHA-256 `8faebe055b0e87bc...`),
  1.638 inválidos pelo PostGIS (gravados como vêm), 0 fora do Brasil, 0 sem `id_estado`; 4 chaves repetidas ganham ordinal. Segunda execução sem mudança (12.874 inalterados).
  Fora da atualização agendada até o usuário decidir.
