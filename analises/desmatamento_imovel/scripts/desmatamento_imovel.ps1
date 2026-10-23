# Desmatamento PRODES por imovel do SICAR -> resultados.desmatamento_imovel. A METODOLOGIA OFICIAL do projeto.
# Documentada em analises/desmatamento_imovel/LEIAME_desmatamento_imovel.md. Reuse SEMPRE este script (nao refaca a conta a mao).
#
# Metodo (resumo): para cada imovel VIGENTE (vigente_ate IS NULL) do SICAR, cruza a geometria DIRETO com todos os
# poligonos VIGENTES de vetorial.prodes_desmatamento que o tocam (SEM pre-filtrar pela ponte prodes_municipio), e grava a
# area geodesica (ST_Area ::geography, em ha) por imovel x ano PRODES x bioma, com pct sobre num_area (teto 999,99).
# PENDENTE = versao vigente do imovel ainda nao processada OU processada com outra edicao do PRODES (catalogo.v_edicoes_prodes).
#
# Uso (PowerShell, a partir de qualquer pasta; roda como postgres no dw-postgis):
#   .\analises\desmatamento_imovel\scripts\desmatamento_imovel.ps1 -UF AC -Simular      calcula e relata, sem gravar
#   .\analises\desmatamento_imovel\scripts\desmatamento_imovel.ps1 -UF AC               grava so os PENDENTES (versoes vigentes ainda nao processadas)
#   .\analises\desmatamento_imovel\scripts\desmatamento_imovel.ps1 -UF AC -Tudo         recalcula a UF inteira (use quando o PRODES ganhar ano novo
#                                                                 ou a metodologia mudar)
#   -Lote 50000   imoveis por lote (cada lote e uma transacao)
# Antes de gravar uma UF grande, faca backup com etiqueta (backup_banco.ps1 -Etiqueta antes-desmat-<uf>).
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z]{2}$')][string]$UF,
    [int]$Lote = 50000,
    [switch]$Simular,
    [switch]$Tudo
)
$ErrorActionPreference = 'Stop'
$UF = $UF.ToUpper()
$raiz = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))

function Psql($sql, $vars = @()) {
    $args2 = @('exec', '-i', 'dw-postgis', 'psql', '-U', 'postgres', '-d', 'data_warehouse', '-v', 'ON_ERROR_STOP=1', '-A', '-t', '-F', '|')
    foreach ($v in $vars) { $args2 += @('-v', $v) }
    $ErrorActionPreference = 'Continue'   # NOTICE do psql vem pelo stderr: nao e erro
    $r = $sql | & docker @args2 2>&1 | ForEach-Object { "$_" }
    $codigo = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($codigo -ne 0) { throw "psql falhou: $($r -join ' ')" }
    $r | Where-Object { $_ -notmatch '^(NOTICE|INSERT|CREATE|ALTER|ANALYZE|DROP|DELETE|UPDATE|BEGIN|COMMIT|ROLLBACK|SET|GRANT|COMMENT)' -and "$_".Trim() }
}
function Log($m) { Write-Host ("[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m) }

$ErrorActionPreference = 'Continue'   # o psql escreve NOTICE no stderr; so o codigo de saida importa
Get-Content (Join-Path $raiz 'analises\desmatamento_imovel\sql\desmatamento_imovel_estrutura.sql') -Raw | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1 -q 2>&1 | Out-Null
$codigoEstrutura = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($codigoEstrutura -ne 0) { throw "nao consegui aplicar a estrutura (analises\desmatamento_imovel\sql\desmatamento_imovel_estrutura.sql)" }

$ufq = $UF
if ((Psql "SELECT count(*) FROM vetorial.sicar_imoveis WHERE cod_estado = '$ufq' AND vigente_ate IS NULL;") -eq '0') { throw "nenhum imovel vigente do SICAR em $UF" }
$anoMax = Psql "SELECT max(year) FROM vetorial.prodes_desmatamento WHERE vigente_ate IS NULL;"
$ed = Psql "SELECT edicoes FROM catalogo.v_edicoes_prodes;"
if (-not $ed) { throw "nao ha edicao do PRODES registrada em catalogo.coletas (rode o pipeline do PRODES antes)" }
$modo = $(if ($Simular) { 'SIMULACAO (nada e gravado)' } else { 'GRAVANDO' }) + $(if ($Tudo) { ' | -Tudo' } else { '' })
Log "UF $UF | PRODES ate $anoMax (edicoes: $ed) | Lote $Lote | $modo"

if ($Tudo -and -not $Simular) {
    Psql "DELETE FROM resultados.desmatamento_imovel_controle WHERE cod_estado = '$ufq';" | Out-Null
    Log "-Tudo: controle da UF zerado (os resultados antigos sao substituidos lote a lote)"
}
$pend = "FROM vetorial.sicar_imoveis s WHERE s.cod_estado = '$ufq' AND s.vigente_ate IS NULL AND s.geom IS NOT NULL" + $(if ($Tudo) { '' } else { " AND NOT EXISTS (SELECT 1 FROM resultados.desmatamento_imovel_controle c WHERE c.id_imovel_sicar = s.id AND c.edicoes_prodes = '$ed')" })
$faixas = @(Psql "SELECT min(id), max(id), count(*) FROM (SELECT s.id, (row_number() OVER (ORDER BY s.id) - 1) / $Lote AS g $pend) t GROUP BY g ORDER BY 1;")
if (-not $faixas.Count) { Log "nada pendente em ${UF}: todas as versoes vigentes ja foram processadas."; return }
Log "$($faixas.Count) lote(s) de ate $Lote imoveis pendentes"

$sqlLote = @'
begin;
create temp table im as
  select s.id, s.cod_imovel, s.num_area, case when st_isvalid(s.geom) then s.geom else st_makevalid(s.geom) end geom
  from vetorial.sicar_imoveis s
  where s.cod_estado = :'uf' and s.vigente_ate is null and s.geom is not null and s.id between :idmin and :idmax
    and (:tudo or not exists (select 1 from resultados.desmatamento_imovel_controle c where c.id_imovel_sicar = s.id and c.edicoes_prodes = :'ed'));
create index on im using gist(geom); analyze im;
create temp table cand as
  select p.id, p.year, p.id_bioma, case when st_isvalid(p.geom) then p.geom else st_makevalid(p.geom) end geom
  from vetorial.prodes_desmatamento p
  where p.vigente_ate is null
    and p.id in (select distinct p2.id from im i join vetorial.prodes_desmatamento p2 on p2.geom && i.geom and p2.vigente_ate is null);
create index on cand using gist(geom); analyze cand;
create temp table res as
  select i.id id_imovel, i.cod_imovel, i.num_area, c.year ano, c.id_bioma,
         sum(st_area(st_intersection(i.geom, c.geom)::geography)) m2
  from im i join cand c on st_intersects(i.geom, c.geom)
  group by i.id, i.cod_imovel, i.num_area, c.year, c.id_bioma
  having sum(st_area(st_intersection(i.geom, c.geom)::geography)) > 0;
delete from resultados.desmatamento_imovel d using im where d.cod_imovel = im.cod_imovel;
insert into resultados.desmatamento_imovel (id_imovel_sicar, cod_imovel, ano, id_bioma, area_desmatada_ha, pct_area_imovel)
  select id_imovel, cod_imovel, ano, id_bioma, round((m2 / 10000)::numeric, 2),
         least(round((m2 / 10000 / nullif(num_area, 0) * 100)::numeric, 2), 999.99)
  from res;
delete from resultados.desmatamento_imovel_controle c using im where c.cod_imovel = im.cod_imovel;
insert into resultados.desmatamento_imovel_controle (id_imovel_sicar, cod_imovel, cod_estado, ano_prodes_max, edicoes_prodes)
  select id, cod_imovel, :'uf', :anomax, :'ed' from im;
select (select count(*) from im) as imoveis, (select count(*) from cand) as poligonos, (select count(*) from res) as linhas, (select count(distinct id_imovel) from res) as com_desmatamento, (select round(sum(m2)/10000) from res) as ha;
'@
$fim = if ($Simular) { 'rollback;' } else { 'commit;' }
$tot = [pscustomobject]@{ imoveis = 0; linhas = 0; com = 0; ha = 0 }
$t0 = Get-Date; $i = 0
foreach ($f in $faixas) {
    $i++; $p = $f -split '\|'
    $r = Psql ($sqlLote + "`n" + $fim) @("uf=$UF", "idmin=$($p[0])", "idmax=$($p[1])", "tudo=$(if ($Tudo) { 'true' } else { 'false' })", "anomax=$anoMax", "ed=$ed")
    $v = ($r | Select-Object -Last 1) -split '\|'
    $tot.imoveis += [long]$v[0]; $tot.linhas += [long]$v[2]; $tot.com += [long]$v[3]; $tot.ha += [double]$v[4]
    Log ("lote {0}/{1}: {2} imoveis, {3} linhas, {4} com desmatamento, {5} ha" -f $i, $faixas.Count, $v[0], $v[2], $v[3], $v[4])
}
Log ("{0} em {1:N1} min: {2} imoveis processados, {3} linhas, {4} imoveis com desmatamento, {5:N0} ha" -f $(if ($Simular) { 'SIMULACAO terminou' } else { 'terminou' }), ((Get-Date) - $t0).TotalMinutes, $tot.imoveis, $tot.linhas, $tot.com, $tot.ha)

if (-not $Simular) {
    Log "=== conferencia da UF"
    Psql @"
SELECT 'imoveis vigentes com geometria', count(*)::text FROM vetorial.sicar_imoveis WHERE cod_estado = '$ufq' AND vigente_ate IS NULL AND geom IS NOT NULL
UNION ALL SELECT 'processados (controle)', count(*)::text FROM resultados.desmatamento_imovel_controle WHERE cod_estado = '$ufq'
UNION ALL SELECT 'vigentes ainda pendentes', count(*)::text FROM vetorial.sicar_imoveis s WHERE cod_estado = '$ufq' AND vigente_ate IS NULL AND geom IS NOT NULL AND NOT EXISTS (SELECT 1 FROM resultados.desmatamento_imovel_controle c WHERE c.id_imovel_sicar = s.id AND c.edicoes_prodes = '$ed')
UNION ALL SELECT 'linhas de desmatamento da UF', count(*)::text FROM resultados.desmatamento_imovel d JOIN vetorial.sicar_imoveis s ON s.id = d.id_imovel_sicar WHERE s.cod_estado = '$ufq'
UNION ALL SELECT 'linhas apontando para versao FECHADA (esperado 0)', count(*)::text FROM resultados.desmatamento_imovel d JOIN vetorial.sicar_imoveis s ON s.id = d.id_imovel_sicar WHERE s.cod_estado = '$ufq' AND s.vigente_ate IS NOT NULL
UNION ALL SELECT 'ha desmatados (soma)', round(sum(area_desmatada_ha))::text FROM resultados.desmatamento_imovel d JOIN vetorial.sicar_imoveis s ON s.id = d.id_imovel_sicar WHERE s.cod_estado = '$ufq';
"@ | ForEach-Object { Write-Host "  $_" }
}
