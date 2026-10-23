# funai/terras_indigenas — histórico

- **2026-09-29** — o shapefile `tis_poligonais` (665 feições) foi baixado à mão do mesmo servidor para uma demanda pontual e ficou no Drive, sem entrar no banco.
- **2026-10-23** — pipeline automatizado criado (`scripts/terras_indigenas.py`) e primeira carga: 665 terras, 0 geometrias anômalas; segunda execução sem nenhuma
  mudança (idempotente). Regra do projeto desde esta data: dado novo só entra por automação direto da fonte; o shapefile antigo do Drive **não** foi
  usado. Descobertas: o servidor barra `GetFeature` sem `count` (403) e não envia o certificado intermediário (`dwlib/certs/sectigo_ov_r36.pem`).
  Primeiro uso do módulo comum `dwlib/espelho.py` (reconciliação do espelho versionado), para as próximas fontes não copiarem a lógica.
