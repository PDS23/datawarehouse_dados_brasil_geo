# mma/unidades_conservacao — histórico

- **2026-10-23** — levantamento de fontes: o CKAN do MMA tem o shapefile do CNUC com link direto só até 2025_08; as edições 2026_03 e 2026_07 estão em links do SharePoint (com token).
- **2026-10-27** — o usuário decidiu manter o dado atualizado (importa tanto quanto a automação total, e a demanda é para um edital) e baixou à mão o zip `cnuc_2026_07.zip` (60,3 MB, 21/08/2026,
  SHA-256 `4d9cbca3f463b1cb...`): **exceção autorizada à regra de só automação** (CLAUDE.md, regra 8). Pipeline criado (`scripts/unidades_conservacao.py`) e primeira carga: 3.576 UCs
  (3.406 polígonos + 170 pontos), 0 geometrias inválidas ou fora do Brasil; segunda execução sem mudança. `--verificar` consulta o CKAN e avisa quando o shapefile ganhar link direto
  (hoje o mais recente com link direto é 2025_08).
