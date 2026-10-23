# ibge/municipios — estados e municípios direto do IBGE

Pipeline `scripts/localidades.py` (ver `scripts_comuns/LEIAME_pipelines.md`): mantém `dim.estados` e
`dim.municipios` em dia com o IBGE, sem download manual.

## Fontes

1. **SIDRA, tabela 6579** (`apisidra.ibge.gov.br`): lista oficial **vigente** de UFs (27) e municípios (5.571) com
   código e nome. É por ela que se descobre um município novo.
2. **Malha territorial** (`geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/`):
   `BR_Municipios_AAAA.zip` (~237 MB) e `BR_UF_AAAA.zip` (~15 MB) do ano mais recente publicado, em SIRGAS 2000
   (EPSG:4674). Só com `--geometria`. Os zips ficam em `bruto/` com manifesto (data, tamanho, SHA-256).

## O que faz e o que não faz

- **Acrescenta** município que existe no IBGE e falta na dimensão; **preenche** a geometria de quem está sem.
- **Nunca altera** nome nem geometria de quem já existe, **a não ser com `--atualizar-geometria`** (ver abaixo);
  diferenças de nome são só relatadas (os 5 nomes antigos foram corrigidos à mão em 15/10/2026).
- **Nunca apaga.** As lagoas Mirim e dos Patos (4300001 e 4300002) vêm da malha, não são municípios na lista do
  SIDRA, e continuam na dimensão (são relatadas como "fora da lista do IBGE").

## Estado em 2026-10-14

- Acrescentado **5101837 Boa Esperança do Norte/MT** (geometria da malha 2025, 4.704,49 km², válida, dentro de MT).
  O SICAR já usava esse código (64 imóveis), que registramos como "inexistente" porque a malha anterior não o tinha.
- Dimensão: 5.573 municípios (5.571 do IBGE + 2 lagoas), todos com geometria, 0 inválidas. A malha 2025 tem os
  mesmos 5.573 territórios.
- **5 nomes diferentes** do IBGE (a dimensão guarda a grafia antiga): 1400605 `São Luiz` x `São Luiz do Anauá`,
  2400208 `Açu` x `Assú`, 2401206 `Arês` x `Arez`, 2802601 `Gracho Cardoso` x `Graccho Cardoso`, 3105509
  `Barão de Monte Alto` x `Barão do Monte Alto`. Não foram alterados.

## Atualizar a malha inteira (`--atualizar-geometria`) — criado e APLICADO em 2026-10-20

**Aplicado em 20/10/2026** (depois do backup `pre-malha-2025`): 2.429 geometrias substituídas e arquivadas em
`dim.malha_anterior`; os 5.573 municípios e as 27 UFs passaram a ter `ano_malha = 2025`; 0 geometrias inválidas.
A ponte PRODES foi refeita inteira em seguida (`analises/ponte_prodes_municipio/scripts/refazer_ponte_municipio.ps1`): 7.027.719 pares (eram
7.028.540); a antiga ficou guardada em `resultados.prodes_municipio_malha_antiga` até o usuário decidir apagá-la.
`vetorial.sicar_imoveis.id_municipio` **não** foi recalculado: numa amostra de ~100 mil imóveis, 1,7% têm o município
gravado diferente do município onde o imóvel está pela malha 2025; o dado gravado é o do CAR (atributo do cadastro),
não derivado da nossa geometria.

Com `--geometria --atualizar-geometria [--ano-malha 2025]`, o script **substitui** as geometrias de municípios e UFs
que mudaram na malha nova. Salvaguardas:
- a geometria antiga vai para `dim.malha_anterior` antes da troca (nada se perde; dá para voltar pelo `id_territorio`);
- `dim.municipios.ano_malha` e `dim.estados.ano_malha` registram de que malha vem cada geometria;
- geometria nova inválida não entra; malha com menos de 5.500 municípios (ou 27 UFs) aborta;
- mede a mudança pela **área da diferença simétrica** entre a antiga e a nova, em fração da área antiga: até 1e-6 =
  igual (só ganha o `ano_malha`), até 0,1% = pequena, acima disso = grande. (O Hausdorff foi testado e é quadrático:
  passou de 9 min no primeiro passo.)
- DDL por administrador: `sql/01_malha_versionada.sql` (coluna `ano_malha` e a tabela `dim.malha_anterior`).

**Simulação de 2026-10-20 (malha 2025 contra o que está na dimensão):**
- UFs: **27 de 27 idênticas** (a dimensão de UFs já era a de 2025).
- Municípios: **3.144 idênticos, 1.380 com mudança pequena (< 0,1% da área) e 1.049 com mudança grande**; no total,
  2.429 seriam substituídos. A dimensão guarda uma malha **mais antiga** que a de 2025 (o ano não foi registrado).
- Maiores mudanças (parte vem da criação de Boa Esperança do Norte): Nova Ubiratã/MT 12.461 → 8.721 km² (−30%), Várzea
  Grande/MT 724 → 940 km², São José do Divino/PI 319 → 391 km², Sambaíba/MA 2.476 → 3.015 km², Seringueiras/RO
  3.774 → 4.444 km².
- **Depende da geometria municipal e teria de ser recalculado depois:** `resultados.prodes_municipio` (a ponte PRODES →
  município, 7.028.540 pares) e a view `vetorial.v_prodes_municipio`. Se `vetorial.sicar_imoveis.id_municipio` depende da
  geometria ou do código que veio do CAR: NÃO VERIFICADO.

## Uso

```powershell
... run --rm etl ibge/municipios/scripts/localidades.py --simular              # só relata, sem baixar a malha
... run --rm etl ibge/municipios/scripts/localidades.py --geometria --simular  # baixa a malha e simula
... run --rm etl ibge/municipios/scripts/localidades.py --geometria            # grava (só preenche o que falta)
... run --rm etl ibge/municipios/scripts/localidades.py --geometria --atualizar-geometria --ano-malha 2025 --simular  # relata o que mudaria
... run --rm etl ibge/municipios/scripts/localidades.py --geometria --atualizar-geometria --ano-malha 2025            # SUBSTITUI (faça backup antes)
```
