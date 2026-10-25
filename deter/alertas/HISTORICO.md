# deter/alertas — histórico

- **2026-10-25** — pipeline criado (`scripts/deter_alertas.py`) a partir do levantamento de fontes de 2026-10-23. Descobertas: o GeoJSON do servidor corta as coordenadas
  em 4 casas (usamos SHAPE-ZIP, com campos truncados em 10 letras); o `gid` não é único (repete entre os biomas, entre os municípios que um polígono cruza e é reutilizado por alertas diferentes), então a chave é (`id_bioma`, `gid`, `chave_linha`) (ver LEIAME); `publish_month` é nulo em 2 alertas do Cerrado (fatia própria). Teste com `--a-partir 2026-09 --simular`:
  9.756 linhas, todas casadas com o anunciado.
- **2026-10-25 (mais tarde)** — a primeira carga completa usou (`id_bioma`, `gid`, município) e descartou 10.152 alertas legítimos da Amazônia (454.201 de 464.353 gravados);
  percebido ao comparar lidos x gravados. Tabela refeita com a chave (`id_bioma`, `gid`, `chave_linha`) e recarregada.
