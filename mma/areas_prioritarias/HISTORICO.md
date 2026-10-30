# mma/areas_prioritarias — histórico

- **2026-10-30** — levantamento: o pacote do CKAN do MMA (atualizado em 21/12/2022) tem 7 zips de shapefile com links diretos (esquemas diferentes) e um zip de listas de ações em CSV (referência, não espacial).
- **2026-10-30** — pipeline criado (`scripts/areas_prioritarias.py`) e primeira carga: 2.081 áreas (2ª atualização), 42 polígonos inválidos (gravados como vêm); segunda execução sem mudança. A caixa de
  conferência foi alargada (latitude -40 a 10) porque a "Área Insuficientemente Conhecida" da zona marinha é legítima e a ultrapassava; a recarga corrigiu só essa área. Fora da atualização agendada
  (edição estática).
