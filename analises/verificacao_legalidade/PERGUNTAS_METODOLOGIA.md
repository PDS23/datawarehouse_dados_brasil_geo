# Pré-análise de legalidade: perguntas de metodologia por camada

Levantamento de 2026-10-28 (ROADMAP, item 16.3). **Respostas do usuário registradas em 2026-11-12** (documento de trabalho "Requisitos_Metodologia", no Drive do
usuário). Cada pergunta tem **Decisão:**; onde ainda não há resposta, está escrito **em aberto**. Onde a resposta precisou de interpretação, ou conflita com outra
decisão, há uma **Nota**. O foco é **cada camada**: o que ela diz, o que vamos considerar e o que falta.

## A. Entrada

1. **Quais entradas aceitamos?** Código do imóvel no SICAR, parcela do SIGEF, polígono de lote (vários talhões), CPF/CNPJ do produtor, município. Todas, ou começamos por uma?
   **Decisão:** código do CAR (um imóvel ou um lote de códigos) e polígono enviado em arquivo espacial (GeoJSON, shapefile e afins).
2. **CPF/CNPJ como entrada:** serve só para as listas por documento (embargos, lista suja) ou também para **achar os imóveis do titular**?
   **Decisão:** só para as listas por documento; não é usado para achar imóveis. **O CPF/CNPJ é opcional** (decisão de 2026-11-12): muitas vezes a demanda chega sem ele, e aí
   roda só a análise espacial do polígono. A verificação tem dois modos, **com** e **sem análise documental** (embargos IBAMA, ICMBio e SEMA-MT por documento, e lista suja
   do MTE), e o resultado sempre diz **se a análise documental foi feita ou não**. Sem documento, os critérios por documento saem como "não verificado", nunca como "passa".
3. **Unidade de resultado:** o lote inteiro, cada talhão ou cada imóvel? Uma reprovação em um talhão reprova o lote?
   **Decisão:** qualquer polígono de entrada (imóvel ou talhão); o resultado sai por polígono. *Em aberto:* se um polígono reprovado reprova o lote.
4. **Geometria de entrada inválida** (auto-interseção, anel aberto): reparamos ou recusamos?
   **Decisão:** reparar sempre (`ST_MakeValid`) e seguir com a análise.
5. **Imóvel do SICAR:** quais status aceitos (ativo, pendente, suspenso, cancelado)? Imóvel cancelado reprova?
   **Decisão:** a análise roda para qualquer status, e o resultado informa o status do CAR. Status diferente de **ativo** ou **pendente** não passa no critério do CAR.
6. **Data de referência:** hoje, a data da produção/colheita ou a do embarque? **Decisão:** em aberto.

## B. Regras comuns de sobreposição

7. **Tolerância:** área mínima e/ou percentual para não acusar ruído de borda?
   **Decisão:** duas versões: **sem tolerância** e **com tolerância de 1%** (a testar, para comparar as duas).
8. **Onde conta a sobreposição:** no imóvel inteiro, ou só na parte produtiva?
   **Decisão:** no polígono que está sendo analisado; para o Brasil, a priori, o imóvel inteiro.
9. **Buffer/entorno:** alguma camada exige distância? **Decisão:** não; só interseção direta.
10. **"Sem dado":** como tratar o que a camada não cobre (SEMA-MT só vale em Mato Grosso; UC só com ponto)? **Decisão:** em aberto.
11. **Medida de área:** `geography` (exata) ou EPSG 5880 (mais rápida)? **Decisão:** em aberto.

## C. Desmatamento — fora desta análise

**Decisão (2026-11-12):** o desmatamento **não entra na pré-análise de legalidade**. Ele fica numa análise separada, a **convergência de evidência**, que é onde o
desmatamento é identificado. As perguntas 12 a 19 (corte de 31/12/2020, definição de floresta, classes do PRODES, MapBiomas Alerta, DETER, desmatamento autorizado,
base de floresta em 2020) passam para essa análise e não são respondidas aqui.

As camadas que o usuário já listou para a convergência de evidência ficam registradas aqui só como ponto de partida:
- **Desmatamento:** PRODES, MapBiomas Alerta e bases globais.
- **Floresta (o que era floresta):** uso do solo do MapBiomas (formação florestal, savânica, silvicultura etc.); regiões fitoecológicas do IBGE 2026
  (`geoftp.ibge.gov.br/informacoes_ambientais/vegetacao/vetores/regioes_fitoecologicas_outras_areas/`); fitofisionomias do RADAM (`dpi.inpe.br/Ambdata/mapa_sipam.php`);
  vegetação do IBGE; bases globais (JRC, SBTN e a tipologia florestal 2020 do Global Nature Watch, publicada como asset no Google Earth Engine).

## D. Imóvel, posse e terra pública (SICAR, SIGEF, INCRA, SFB)

20. **Sobreposição entre CAR:** reprova? **Decisão:** não reprova; o resultado leva um **alerta de sobreposição**.
21. **SIGEF/SNCI:** exigir o imóvel certificado para comprovar posse? **Decisão:** em aberto.
22. **Direitos de uso da terra** (matrícula, CCIR, ITR): ficam fora ou entram como declaração do produtor? **Decisão:** em aberto.
23. **Florestas públicas não destinadas:** sobreposição reprova? **Decisão:** não reprova; o resultado leva um **alerta**.
24. **Assentamentos:** sobreposição reprova? **Decisão:** não são analisados.
25. **Outras terras públicas:** terras da União, áreas militares, faixa de fronteira.
    **Decisão:** terras da União e faixa de fronteira **não são analisadas**; **área militar reprova**. *Nota:* ainda não há camada de áreas militares no banco: é preciso pesquisar a fonte.

## E. Territórios protegidos (FUNAI, CNUC, quilombolas)

26. **Terra indígena, fases que contam:** **Decisão:** todas as fases que a camada da FUNAI traz; sem buffer (pergunta 9).
27. **Unidade de conservação:** só proteção integral reprova, ou também uso sustentável?
    **Decisão (revista em 2026-11-12):** a regra é **por grupo**, não por categoria (Lei 9.985/2000, SNUC): **Proteção Integral reprova**, **Uso Sustentável passa**
    (pode haver produção de uso sustentável dentro dela; era o motivo de liberar a APA). Vale para todas as esferas (federal, estadual, municipal).
    Categorias no CNUC (só polígonos): Proteção Integral = Estação Ecológica, Reserva Biológica, Parque, Monumento Natural, Refúgio de Vida Silvestre;
    Uso Sustentável = APA, ARIE, Floresta (Nacional/Estadual/Municipal), Reserva Extrativista, Reserva de Fauna, Reserva de Desenvolvimento Sustentável, RPPN.
    **Alerta (decidido em 2026-11-12):** RPPN (gravada em perpetuidade para conservação, só pesquisa e visitação), Reserva Extrativista, RDS, Floresta e Reserva de
    Fauna (posse e domínio públicos, uso só pelas populações tradicionais ou manejo florestal) não comportam produção agropecuária comum: **passam, mas com alerta**
    no resultado. APA e ARIE passam sem alerta.
28. **UC sem polígono** (170 só com ponto): **Decisão:** usar só a camada de polígonos; as UCs só com ponto ficam fora.
29. **Quilombolas:** substituto enquanto o INCRA está fora do ar.
    **Decisão:** territórios quilombolas do **IBGE 2022** (decisão de 2026-11-12, já carregados), até o INCRA voltar. *Nota:* o documento de requisitos diz "camada de territórios quilombolas do MapBiomas", mas o MapBiomas não publica os limites dos territórios (só estatísticas por território, a partir de IBGE e INCRA); por isso prevalece o IBGE 2022.
30. **Outras áreas protegidas** (áreas prioritárias do MMA, reserva legal, APP): **Decisão:** não são analisadas.

## F. Embargos, infrações e trabalho (IBAMA, ICMBio, SEMA-MT, MTE)

31. **Embargo vigente:** o que exclui (desembargado, cancelado, desembargo parcial)? Há data limite? **Decisão:** em aberto.
32. **Por área e por documento:** **Decisão:** os dois, no IBAMA e no ICMBio (polígono e CPF/CNPJ). *Em aberto:* o que fazer com o embargo só com ponto (42 mil no IBAMA).
33. **Titular:** CPF/CNPJ exato, raiz do CNPJ, sócios, arrendatários? **Decisão:** em aberto.
34. **ICMBio:** o julgamento muda alguma coisa? **Decisão:** em aberto.
35. **Embargos estaduais fora de Mato Grosso:** **Decisão:** fazer o levantamento das fontes de embargo estadual de **MG, MS, BA, SP, ES, RJ e RO**.
36. **Autos de infração** sem embargo: contam? **Decisão:** em aberto.
37. **Lista suja do trabalho escravo:** só quem consta hoje? O TAC fica como lacuna? **Decisão:** a lista suja entra; *em aberto:* quem saiu há pouco e o TAC.
38. **Outras camadas a pesquisar** (mineração/ANM, terras da União/SPU, focos de queimada, Fundação Palmares)? **Decisão:** em aberto. A SPU sai, porque a
    pergunta 25 decidiu que terras da União não são analisadas (ela só entrou na lista como sugestão deste levantamento, no ROADMAP 16.5).

## G. Tempo e frescor

39. **Defasagem tolerada** de cada fonte: **Decisão:** em aberto.
40. **Foto por data:** precisamos reproduzir o resultado de uma data passada? **Decisão:** em aberto.

## H. Saída, privacidade e validação

41. **Formato do resultado:** "passa / não passa / sem dado", com área sobreposta e identificador da feição. **Decisão:** em aberto. Já decidido em outras perguntas: o resultado tem também **alertas que não reprovam** (CAR sobreposto, floresta pública não destinada) e informa o status do CAR.
42. **Dado pessoal no resultado:** pode aparecer o nome do embargado? **Decisão:** em aberto.
43. **Regras por cliente:** **Decisão:** em aberto.
44. **Validação:** contra quais relatórios de referência? **Decisão:** em aberto.

## Resumo das regras decididas

| Camada | Regra |
|---|---|
| CAR (SICAR) | analisa qualquer status; só ativo ou pendente passa; CAR sobreposto vira alerta |
| Terra indígena (FUNAI) | todas as fases da camada reprovam |
| Unidade de conservação (CNUC) | só polígonos; por grupo: Proteção Integral reprova, Uso Sustentável passa (APA e ARIE sem alerta; RPPN, RESEX, RDS, Floresta e Reserva de Fauna com alerta) |
| Quilombola | IBGE 2022 até o INCRA voltar; reprova |
| Embargos IBAMA e ICMBio | por polígono; por CPF/CNPJ só quando o documento vier |
| Embargos SEMA-MT | por polígono; por CPF/CNPJ só quando o documento vier (vale para Mato Grosso) |
| Lista suja (MTE) | por CPF/CNPJ, só quando o documento vier |
| CPF/CNPJ | opcional; o resultado diz se a análise documental foi feita; sem documento, os critérios por documento saem "não verificado" |
| Floresta pública não destinada (SFB) | alerta, não reprova |
| Área militar | reprova (camada a pesquisar) |
| Assentamentos, terras da União, faixa de fronteira, APP, reserva legal, áreas prioritárias | não analisados |
| Desmatamento | fora: vai para a convergência de evidência |
| Geral | reparar geometria; sem buffer; duas versões (sem tolerância e 1%) |
