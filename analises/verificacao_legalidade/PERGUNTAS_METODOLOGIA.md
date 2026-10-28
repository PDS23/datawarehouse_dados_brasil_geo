# Pré-análise de legalidade: perguntas de metodologia por camada

Levantamento de 2026-10-28 (ROADMAP, item 16.3). Cada pergunta tem **Decisão:** em branco para ser preenchida; nada aqui é decidido ainda. O foco é **cada camada**: o que ela diz, o que vamos
considerar e o que falta. As fontes já estão no banco (11 dos 12 critérios do relatório de referência); o que falta é a regra.

## A. Entrada

1. **Quais entradas aceitamos?** Código do imóvel no SICAR, parcela do SIGEF, polígono de lote (vários talhões), CPF/CNPJ do produtor, município. Todas, ou começamos por uma? Decisão:
2. **CPF/CNPJ como entrada:** serve só para as listas por documento (embargos, lista suja) ou também para **achar os imóveis do titular**? Existe alguma fonte pública que ligue o documento ao imóvel (o CAR público não traz o titular)? Decisão:
3. **Unidade de resultado:** o lote inteiro, cada talhão ou cada imóvel? Uma reprovação em um talhão reprova o lote? Decisão:
4. **Geometria de entrada inválida** (auto-interseção, anel aberto): reparamos com `ST_MakeValid` e avisamos, ou recusamos? Decisão:
5. **Imóvel do SICAR:** quais status aceitos (ativo, pendente, suspenso, cancelado)? Imóvel cancelado reprova? Decisão:
6. **Data de referência:** hoje, a data da produção/colheita ou a do embarque? As fontes são retrato de hoje (o histórico de versões dura 30 dias): basta o retrato de hoje? Decisão:

## B. Regras comuns de sobreposição

7. **Tolerância:** área mínima (ha) e/ou percentual do imóvel para não acusar ruído de borda entre bases de escalas diferentes? Igual para todas as camadas ou por camada? Decisão:
8. **Onde conta a sobreposição:** no imóvel inteiro, ou só na parte produtiva (cruzando com o uso do solo)? Decisão:
9. **Buffer/entorno:** alguma camada exige distância (zona de amortecimento de UC, entorno de terra indígena), ou só interseção direta? Decisão:
10. **"Sem dado":** como tratar o que a camada não cobre (SEMA-MT só vale em Mato Grosso; DETER só Amazônia e Cerrado; UC só com ponto)? Aprova, reprova ou marca "sem dado"? Decisão:
11. **Medida de área:** `geography` (exata) ou EPSG 5880 (mais rápida)? Qual é a oficial do relatório? Decisão:

## C. Desmatamento (PRODES, DETER, MapBiomas Alerta)

12. **Corte de 31/12/2020:** vale `image_date > 2020-12-31` ou o ano PRODES 2021 em diante (que inclui agosto a dezembro de 2020)? Decisão:
13. **Definição de floresta:** só desmatamento de **floresta** (como a regra europeia define) ou qualquer supressão de vegetação nativa (inclui savana e campo do Cerrado)? Isso muda o resultado no Cerrado. Decisão:
14. **Qual classe do PRODES conta** (desmatamento, resíduo, incremento)? Decisão:
15. **Mais de uma fonte acusa:** basta uma reprovar, ou exige confirmação cruzada? Decisão:
16. **MapBiomas Alerta:** só alerta publicado/validado (`status_name`), ou também em análise? E o que fazer com alerta refutado? Decisão:
17. **DETER:** entra como sinal (alerta recente, ainda fora do PRODES) ou fica de fora por não ser o dado oficial? Inclui degradação e cicatriz de queimada? Decisão:
18. **Desmatamento autorizado** (autorização de supressão): descontamos? Não temos a camada (os dados de autorização são estaduais): aceitamos a lacuna e registramos? Decisão:
19. **Base de floresta em 2020:** precisamos de uma referência para saber o que *era* floresta em 31/12/2020. Temos MapBiomas só para 1985, 2008, 2015 e 2025 (falta 2020). Baixamos MapBiomas 2020 (e 2021 a 2024), ou usamos o mapa de floresta 2020 do JRC (referência da UE)? Decisão:

## D. Imóvel, posse e terra pública (SICAR, SIGEF, INCRA, SFB)

20. **Sobreposição entre CAR** (dois imóveis no mesmo lugar): reprova? Quem prevalece? Decisão:
21. **SIGEF/SNCI:** exigir o imóvel certificado para comprovar posse? A camada está bloqueada (INCRA fora do ar): qual alternativa aceitamos enquanto isso, ou marcamos "sem dado"? Decisão:
22. **Direitos de uso da terra** (matrícula, CCIR, ITR): não há camada pública; ficam fora ou entram como declaração do produtor? Decisão:
23. **Florestas públicas não destinadas** (CNFP, tipo B; glebas arrecadadas): sobreposição reprova? Decisão:
24. **Assentamentos** (INCRA e CNFP): sobreposição reprova ou é normal (o produtor pode ser assentado)? Decisão:
25. **Outras terras públicas:** terras da União (SPU), áreas militares, faixa de fronteira: entram? Decisão:

## E. Territórios protegidos (FUNAI, CNUC, quilombolas)

26. **Terra indígena, fases que contam** (regularizada, homologada, declarada, delimitada, em estudo, restrição de uso): quais? Há buffer? Decisão:
27. **Unidade de conservação:** só proteção integral reprova, ou também uso sustentável (APA liberada; RESEX, FLONA, RDS)? UC municipal e estadual contam como federal? Decisão:
28. **UC sem polígono** (170 só com ponto): ignoramos, usamos um raio ou marcamos "sem dado"? Decisão:
29. **Quilombolas:** o território do INCRA está bloqueado. Aceitamos como substituto a base do IBGE (só localidades em ponto), os imóveis de povos e comunidades tradicionais do SICAR, ou marcamos a lacuna? Decisão:
30. **Outras áreas protegidas:** áreas prioritárias do MMA, reserva legal e APP declaradas no CAR, hidrografia (APP): entram no escopo? Decisão:

## F. Embargos, infrações e trabalho (IBAMA, ICMBio, SEMA-MT, MTE)

31. **Embargo vigente:** o que exclui (desembargado, cancelado, desembargo parcial)? Há data limite (embargo muito antigo ainda vale)? Decisão:
32. **Por área e por documento:** aplicamos os dois? Os **embargos sem geometria** (cerca de 15 mil no IBAMA e 278 no ICMBio) só pegam pela busca de documento. E o embargo só com ponto (42 mil no IBAMA): ignora, usa um raio ou só alerta? Decisão:
33. **Titular:** casamos pelo CPF/CNPJ exato, ou também pela **raiz do CNPJ** (matriz e filiais) e por sócios? Proprietário anterior e arrendatário contam? Decisão:
34. **ICMBio:** o julgamento (homologado em 1ª/2ª instância) muda alguma coisa? Decisão:
35. **Embargos estaduais fora de Mato Grosso** (Pará, Amazonas, Rondônia, Tocantins, Maranhão, Bahia, Minas...): quais estados entram no escopo, e pesquisamos as fontes? Decisão:
36. **Autos de infração** sem embargo (IBAMA e ICMBio): contam como "regra ambiental" descumprida? Decisão:
37. **Lista suja do trabalho escravo:** só quem consta hoje, ou também quem saiu há pouco? O cadastro em ajustamento de conduta (TAC) não está disponível: aceitamos a lacuna? Decisão:
38. **Outras camadas de legalidade a pesquisar:** mineração (ANM), terras da União (SPU), focos de queimada (INPE), Fundação Palmares (certidões quilombolas), embargos de outros órgãos. Quais entram no escopo agora? Decisão:

## G. Tempo e frescor

39. **Defasagem tolerada** de cada fonte (DETER é diário, MapBiomas semanal, PRODES anual, lista suja semestral): o resultado registra a data de cada uma? Há limite de "fonte velha demais"? Decisão:
40. **Foto por data:** precisamos reproduzir o resultado de uma data passada? Se sim, a retenção de 30 dias das versões fechadas não basta: guardamos o resultado (e os ids das versões usadas) em `resultados`. Decisão:

## H. Saída, privacidade e validação

41. **Formato do resultado:** por critério e por imóvel, "passa / não passa / sem dado", com a área sobreposta e o identificador da feição que causou o bloqueio. Basta, ou também uma nota/score? Qualquer reprovação reprova o imóvel? Decisão:
42. **Dado pessoal no resultado:** pode aparecer o nome do embargado? Ou só o identificador do termo e quem tem acesso ao banco vai ao `consultar_embargo.py`? Decisão:
43. **Regras por cliente:** a aprovação é definida pelo cliente (o relatório de referência diz isso). As regras ficam num arquivo de configuração por cliente, com um padrão? Decisão:
44. **Validação:** contra quais relatórios de referência (Lote 14 do CECAFÉ, o relatório comercial) e qual diferença aceitamos? Como explicamos a diferença? Decisão:
