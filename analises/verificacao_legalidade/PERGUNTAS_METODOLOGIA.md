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
   **Decisão:** qualquer polígono de entrada (imóvel ou talhão). **Cada polígono é analisado sozinho**, independentemente dos outros do mesmo lote, e o resultado é
   sempre por polígono; o lote só mostra a contagem (ex.: 12 passam, 1 reprova), sem resultado próprio.
4. **Geometria de entrada inválida** (auto-interseção, anel aberto): reparamos ou recusamos?
   **Decisão:** reparar sempre (`ST_MakeValid`) e seguir com a análise.
5. **Imóvel do SICAR:** quais status aceitos (ativo, pendente, suspenso, cancelado)? Imóvel cancelado reprova?
   **Decisão:** a análise roda para qualquer status, e o resultado informa o status do CAR. Status diferente de **ativo** ou **pendente** não passa no critério do CAR.
6. **Data de referência:** hoje, a data da produção/colheita ou a do embarque?
   **Decisão:** a data em que a análise roda. **Com rastreabilidade para auditoria:** rodar de novo no futuro tem de dar o mesmo resultado. Para isso, o usuário propôs
   **versão por fonte** e **versão do banco = o conjunto das versões das fontes** naquele momento, com **backup só das fontes que mudaram** (e não do banco inteiro).
   Desenho no ROADMAP, item 19. Cobre também as perguntas 39 e 40.

## B. Regras comuns de sobreposição

7. **Tolerância:** área mínima e/ou percentual para não acusar ruído de borda?
   **Decisão:** duas versões: **sem tolerância** e **com tolerância de 1%** (a testar, para comparar as duas).
8. **Onde conta a sobreposição:** no imóvel inteiro, ou só na parte produtiva?
   **Decisão:** no polígono que está sendo analisado; para o Brasil, a priori, o imóvel inteiro.
9. **Buffer/entorno:** alguma camada exige distância? **Decisão:** não; só interseção direta.
10. **"Sem dado":** como tratar o que a camada não cobre?
    **Decisão:** "não se aplica" (fora da cobertura por definição) e "sem dado" (a fonte deveria cobrir e não cobre) ficam separados, nunca "passa". **Camada estadual
    só roda no próprio estado:** um imóvel de MG não é cruzado com a SEMA-MT e o resultado dele não cita a SEMA-MT; ele é cruzado com o órgão de MG que tem a mesma
    função (a levantar, pergunta 35). Cada camada estadual declara a UF que cobre.
11. **Medida de área:** **Decisão:** área geodésica (`geography`, sobre o elipsoide).

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
21. **SIGEF/SNCI:** exigir o imóvel certificado para comprovar posse? **Decisão:** fica fora da análise.
22. **Direitos de uso da terra** (matrícula, CCIR, ITR): **Decisão:** ficam fora; o resultado avisa que a análise não cobre a documentação fundiária.
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

31. **Embargo vigente:** **Decisão:** vigente = sem desembargo e sem cancelamento, **de qualquer data** (sem data limite). Desembargados e cancelados aparecem no
    resultado só como informação, sem reprovar. Na SEMA-MT, a camada de desembargadas tira o embargo correspondente.
32. **Por área e por documento:** **Decisão:** os dois, no IBAMA e no ICMBio (polígono e CPF/CNPJ). **Embargo só com ponto** dentro do polígono vira **alerta**, sem
    reprovar (o ponto não diz a área embargada); embargo sem nenhuma geometria só é achado pelo documento.
33. **Titular:** **Decisão:** CPF/CNPJ exato reprova; mesma raiz de CNPJ (matriz e filiais) vira alerta; sócios, arrendatários e proprietários anteriores ficam fora.
34. **ICMBio:** o julgamento muda alguma coisa? **Decisão:** não; embargo na camada conta, e o julgamento sai no resultado como informação.
35. **Embargos estaduais fora de Mato Grosso:** **Decisão:** fazer o levantamento das fontes de embargo estadual de **MG, MS, BA, SP, ES, RJ e RO**.
36. **Autos de infração** sem embargo (IBAMA e ICMBio): **Decisão:** ficam fora.
37. **Lista suja do trabalho escravo:** **Decisão:** só quem consta na edição atual; a lacuna do cadastro em ajustamento de conduta (TAC) é aceita e registrada no resultado.
38. **Outras camadas a pesquisar** (mineração/ANM, terras da União/SPU, focos de queimada, Fundação Palmares)? **Decisão:** todas fora por enquanto (a SPU já tinha
    saído pela pergunta 25).

## G. Tempo e frescor

39. **Defasagem tolerada** de cada fonte: **Decisão:** o resultado registra a data de cada fonte e há um **limite por fonte**: passou dele, a fonte sai como
    "desatualizada". Limites propostos por fonte, a aprovar, no ROADMAP item 19.
40. **Foto por data:** **Decisão:** sim. O resultado de cada análise é guardado no banco com a versão de cada fonte usada, e a análise tem de ser reproduzível
    (pergunta 6, ROADMAP item 19).

## H. Saída, privacidade e validação

41. **Formato do resultado:** **Decisão:** por polígono e por critério, com os estados passa, reprova, alerta, não verificado, não se aplica e sem dado, a área
    sobreposta e o identificador da feição; resultado geral do polígono = qualquer reprovação reprova; sem nota ou pontuação. Sai em **planilha, GeoJSON** (com as
    sobreposições) **e PDF** tipo relatório. O resultado informa também o status do CAR e se a análise documental foi feita.
42. **Dado pessoal no resultado:** **Decisão:** não aparece nome nem documento do embargado; só o número do termo de embargo. Quem tem acesso ao banco consulta o titular.
43. **Regras por cliente:** **Decisão:** um perfil padrão (esta metodologia) e um arquivo de configuração por cliente que muda o que reprova e o que é alerta;
    começa só com o padrão.
44. **Validação:** **Decisão:** comparar com os resultados que já temos do CECAFÉ, **todos os lotes**. *A conferir:* quais critérios desta análise os resultados do
    CECAFÉ cobrem (o notebook v4 usa CAR, PRODES e MapBiomas Alerta, que é desmatamento); a regra de diferença aceita ficou sem resposta, e o padrão proposto é
    explicar cada diferença por escrito, sem percentual.

## Resumo das regras decididas

| Camada | Regra |
|---|---|
| CAR (SICAR) | analisa qualquer status; só ativo ou pendente passa; CAR sobreposto vira alerta |
| Terra indígena (FUNAI) | todas as fases da camada reprovam |
| Unidade de conservação (CNUC) | só polígonos; por grupo: Proteção Integral reprova, Uso Sustentável passa (APA e ARIE sem alerta; RPPN, RESEX, RDS, Floresta e Reserva de Fauna com alerta) |
| Quilombola | IBGE 2022 até o INCRA voltar; reprova |
| Embargos IBAMA e ICMBio | vigente = sem desembargo nem cancelamento, de qualquer data; por polígono (ponto vira alerta) e por CPF/CNPJ quando o documento vier (exato reprova, raiz do CNPJ alerta); julgamento do ICMBio só informa |
| Embargos estaduais | só rodam no estado da camada (SEMA-MT só para MT); outros estados a levantar |
| Lista suja (MTE) | por CPF/CNPJ, só quando o documento vier; só a edição atual; lacuna do TAC aceita |
| Fora | SIGEF, direitos de uso da terra (com aviso), autos de infração, ANM, queimadas, Fundação Palmares |
| CPF/CNPJ | opcional; o resultado diz se a análise documental foi feita; sem documento, os critérios por documento saem "não verificado" |
| Floresta pública não destinada (SFB) | alerta, não reprova |
| Área militar | reprova (camada a pesquisar) |
| Assentamentos, terras da União, faixa de fronteira, APP, reserva legal, áreas prioritárias | não analisados |
| Desmatamento | fora: vai para a convergência de evidência |
| Geral | reparar geometria; sem buffer; duas versões (sem tolerância e 1%); área geodésica; cada polígono analisado sozinho |
| Resultado | por polígono e critério (passa, reprova, alerta, não verificado, não se aplica, sem dado); planilha, GeoJSON e PDF; sem nome do embargado; perfil padrão + configuração por cliente |
| Tempo | data da execução; resultado guardado com a versão do banco; limite de defasagem por fonte (ROADMAP item 19) |
| Validação | todos os lotes já analisados do CECAFÉ (conferir quais critérios cobrem) |
