# sema_mt/areas_embargadas — histórico

- **2026-10-27** — levantamento: o WFS do Geoportal exige `authkey`, publicada pela própria SEMA nos links do catálogo GeoNetwork; duas camadas (embargadas e desembargadas), SHAPE-ZIP de ~10 e ~6 MB.
- **2026-10-27** — pipeline criado (`scripts/areas_embargadas.py`) e primeira carga: 8.357 embargadas (7.636 CPFs só hash, 555 CNPJs, 0 polígonos inválidos) e 4.729 desembargadas (1 fora de MT);
  segunda execução sem mudança nas duas. Duas tabelas, uma por camada, para ninguém contar embargo encerrado como vigente. Achado e corrigido em `dwlib/espelho.py`: as tabelas temporárias
  `_alt`, `_aus` e `_reab` sobreviviam ao commit e a segunda camada, na mesma conexão, falhava (agora são `ON COMMIT DROP`); o módulo também ganhou `com_geometria=False` para tabelas sem geometria.
