# ibge/sidra — histórico

- **2026-10-21** — desenho da camada genérica aprovado (ROADMAP, item 12): uma tabela de valores particionada por tabela do SIDRA, dimensões `dim.sidra_*`,
  ids em vez de texto, views tipadas por tema. Motivo: o Censo Agropecuário tem 1.407 tabelas e uma tabela tipada por tabela do SIDRA não escala.
- **2026-10-23** — camada criada (`sql/01_camada_generica.sql`) e pipeline único (`scripts/sidra.py`). Piloto: tabela 6956 do Censo 2017 (laranja e dois outros
  produtos) recarregada pela camada e conferida contra `tabular.ibge_censoagro2017_estab_lavoura_perm`. 
  - Conferência: a visão sobre a camada devolveu 55.720 linhas e as mesmas somas da tabela antiga (320.273 e 616.694 estabelecimentos); comparação linha a linha
    nos dois sentidos sem nenhuma diferença; soma dos municípios = total do Brasil em todas as células. Reexecução: 0 versões novas, 0 fechadas, 0 reabertas.
  - Troca (com o "sim" do usuário): `tabular.ibge_censoagro2017_estab_lavoura_perm` passou a ser a **visão** sobre `tabular.sidra_valor` (mesmas colunas, sem o `id`);
    a tabela antiga foi apagada (backup `pre-sidra` feito antes). O script `ibge/censo_agropecuario/scripts/censo_agropecuario.py` (e seu `config.yaml` e `sql/01_esquema.sql`)
    foi **removido** com o "sim" do usuário, junto com `dim.produto_censo_lavoura_perm` e `dim.grupo_area_total` (as categorias e as faixas de área estão em `dim.sidra_categoria`, classificação 220).
- **2026-10-23 (passo 5)** — cultura canônica: `dim.cultura_equivalencia` + 22 culturas só do Censo em `dim.cultura` (`sql/03_cultura_equivalencia.sql`); a PAM (c782) entrou como
  classificação do SIDRA só nas dimensões (os valores continuam em `tabular.ibge_pam`). **Desvio do desenho aprovado (confirmado pelo usuário em 2026-10-23):** em vez de renumerar as 238 mil linhas da PAM, o id canônico
  das culturas que a PAM já tem **é o código c782** (ids novos só para as do Censo, a partir de 900001): sem troca de ids, sem quebrar consultas e scripts que usam 40124 etc.
  Se um dia quiserem ids sem relação com o SIDRA, a renumeração continua possível (backup + "sim"). `pam.py` registra culturas novas da PAM na equivalência sozinho.
  Conferência: Laranja 2017 junta Censo (55.912 estabelecimentos com 50 pés ou mais) e PAM (632.939 ha colhidos) pelo `id_cultura`.
- **Pendências do desenho:** retenção das versões fechadas de `tabular.sidra_valor` (a chave é composta e o `limpar_versoes_fechadas.py` só aceita chave simples); LSPA direto na camada.
- **2026-10-23** — retenção das versões fechadas reduzida de 365 para **30 dias** (ambos os prazos), e atualização das fontes vivas decidida a cada 15 dias (ROADMAP item 13).
- **2026-10-27** — primeiras tabelas do **Censo Demográfico** (13 tabelas: 202, 9923, 9515, 10295, 10268, 10299, 10261, 9542, 9543, 10061, 6804, 6805, 6806),
  sob demanda (pedido de análise regional); cada uma em município, UF e Brasil. `sidra.py` passou a aceitar tabela **sem**
  classificação "pedido" sem `--cat` (caso da 9515, que não tem classificações): o recorte inteiro já está fixado no `config.yaml`. Tabelas com classificação
  "pedido" continuam exigindo `--cat`.
- **2026-11-05** — **PEVS** (Produção da Extração Vegetal e da Silvicultura): tabelas 289, 291 e 5930, todos os produtos, 2016-2025, em município, UF e Brasil,
  sob demanda (pedido de análise regional). A 289 quebrou o `sidra.py` na 1ª tentativa: na PEVS a **unidade muda por categoria** (toneladas,
  m³...) e o "Total" da quantidade vem sem unidade (`MC` vazio, valor `..`). Correção: `MC` vazio vira `id_unidade` NULL; todas as unidades vistas na
  enumeração entram em `dim.unidade` (antes, só a 1ª de cada variável); a unidade certa de cada valor é a da linha em `sidra_valor`, e a de
  `dim.sidra_variavel` é só a 1ª vista.
- **2026-11-05** — **recorte territorial** no `sidra.py` (`--locais`), pedido pelo usuário: municípios (7 dígitos, n6), UFs (n3) ou todos os municípios de UFs
  (n6). A reconciliação de versões passa a ter os locais no escopo (sem isso, carregar 7 municípios fecharia as versões dos outros 5.563); a conferência
  com o total do Brasil é pulada no recorte. Testado em simulação contra a 9515 (dados nacionais já gravados): 7 municípios, municípios do PA, 2 UFs e a
  10299 com `--cat`, todos com 0 versões fechadas fora do recorte. Os dados nacionais já carregados (Censo de 27/10, PEVS) ficam: o usuário quer reusá-los.
