# ibge/territorios_quilombolas — histórico

- **2026-11-12** — decisão: o acervo fundiário do INCRA segue fora do ar (INCRA e SERPRO confirmaram manutenção do código PHP, sem previsão, com volta garantida) e o MapBiomas não distribui limites quilombolas
  (conferido nas páginas de downloads, nos assets do Earth Engine e no toolkit). A base do IBGE, achada no levantamento da INDE (30/10), vira o escape para o critério 12 da legalidade.
- **2026-11-12** — pipeline criado (`scripts/territorios_quilombolas.py`) e carga: camada `CGMAT:qg_2022_620_territorioquilombola__v02`, **495 territórios, 25 UFs, 0 geometrias anômalas ou inválidas**; segunda
  execução sem mudança (idempotente). A camada traz geometria com Z (guardada em 2D). O pipeline descobre a camada de maior ano e versão no `GetCapabilities`, então uma edição nova entra sozinha.
  Camada publicada no GeoServer por view sem dado pessoal (`vetorial.v_ibge_territorios_quilombolas`), estilo `territorio_quilombola`. Fora da atualização agendada (edição do IBGE, sem periodicidade); `--verificar` mostra
  se há edição nova.
