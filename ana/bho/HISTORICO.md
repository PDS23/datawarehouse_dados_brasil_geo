# ana/bho — histórico

- **2026-10-30** — levantamento: o catálogo de metadados da ANA tem várias versões da BHO. A **BHO 2017 (a do ROADMAP) está marcada "Desatualizada"**; a atual é a BHO multiescalas 6 (4 GB de trechos
  e 20 GB de áreas) e há a BHO 250 (1:250.000, versão 02_03, dez/2023; 1,1 GB de trechos e 3,7 GB de áreas). O ROADMAP dizia "uns 3 GB": na verdade a base completa tem de 6 a 40 GB conforme a escala.
- **2026-10-30** — decisão de volume (conservadora, avisada ao usuário): BHO 250, só trechos de drenagem, cursos d'água, linha de costa e bacias Otto níveis 1 a 6 (2,4 milhões de feições); áreas de contribuição
  e pontos de drenagem ficam sob demanda. Pipeline criado (`scripts/bho.py`) e carga da versão 02_03 (números no LEIAME). Fora da atualização agendada (edição estática).
- **2026-10-30** — carga da versão 02_03: 1.614.231 trechos, 807.103 cursos d'água, 25 trechos de linha de costa e 23.608 bacias Otto (níveis 1 a 6), 0 geometrias inválidas. Achados: a fonte repete 31 `cotrecho`,
  15 `idcda` e os 25 segmentos da costa têm o mesmo código (a chave virou `chave_linha`, com ordinal); a primeira carga usou a caixa do Brasil e anulou 20.536 geometrias de rios transfronteiriços, e a trava
  de chave abortou as tentativas anteriores. A caixa foi alargada para a América do Sul e a recarga restaurou as geometrias (1 + 293 + 6.790 + 13.452 alterações, o resto inalterado). Fora da agenda (edição estática).
