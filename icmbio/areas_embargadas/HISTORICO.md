# icmbio/areas_embargadas — histórico

- **2026-10-27** — levantamento: camada pública no ArcGIS Online do ICMBio (14.779 polígonos, `maxRecordCount` 2.000), com nome e CPF/CNPJ do autuado.
- **2026-10-27** — pipeline criado (`scripts/areas_embargadas.py`) e primeira carga: 14.779 polígonos em 18 s de download; CPF só como hash (11.022), CNPJ 1.081; 278 sem geometria, 444 inválidos,
  18 sem UF; 1.218 chaves com ordinal; segunda execução sem mudança. Criado o módulo comum `dwlib/documento.py` (limpeza do documento e HMAC do CPF, a mesma chave do IBAMA): 586 CPFs casam com
  o IBAMA. Criado `infra/scripts/consultar_documento.py` (busca por CPF/CNPJ nas duas fontes).
