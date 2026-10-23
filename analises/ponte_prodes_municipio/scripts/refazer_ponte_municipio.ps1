# Refaz a ponte PRODES x municipio INTEIRA com a geometria atual de dim.municipios (ex.: depois de trocar a malha).
# Mesmo metodo de construir_ponte_municipio.sql (ST_Intersects, lotes por bioma e faixa de id, varios em paralelo),
# mas como script reproduzivel e SEM derrubar a ponte atual:
#   1) constroi resultados.prodes_municipio_nova ao lado da atual (o GeoServer segue lendo a atual);
#   2) fecha (indices, chaves estrangeiras, ANALYZE) e VALIDA contra a atual;
#   3) so com -Trocar: renomeia a atual para prodes_municipio_malha_antiga (NAO apaga), poe a nova no lugar e
#      recria a view vetorial.v_prodes_municipio com as mesmas permissoes. Apagar a antiga e decisao a parte.
#
# Rodar como o usuario do Windows (usa docker exec no dw-postgis, como postgres pelo socket local):
#   .\analises\ponte_prodes_municipio\scripts\refazer_ponte_municipio.ps1                 constroi e valida (nao troca nada)
#   .\analises\ponte_prodes_municipio\scripts\refazer_ponte_municipio.ps1 -Trocar         depois de validar, faz a troca
#   -Paralelo 4  (lotes simultaneos)   -Lote 250000  (poligonos por lote)
# Idempotente por lote (ON CONFLICT DO NOTHING + indice unico). Se a tabela _nova ja existe, pare e olhe: nao a apaga.
#   -SufixoAntiga carga_manual_antiga          sufixo do nome com que a ponte atual e guardada na troca (prodes_municipio_<sufixo>); padrao: malha_antiga
#   -Origem prodes_novo.prodes_desmatamento   tabela PRODES de onde sai a ponte (padrao: vetorial.prodes_desmatamento). Usado ANTES da troca
#                                             do PRODES: a ponte nova ja nasce apontando para a tabela nova (a chave estrangeira acompanha a tabela).
# So poligonos VIGENTES (vigente_ate IS NULL) entram na ponte; a view v_prodes_municipio tambem mostra so os vigentes.
param([int]$Paralelo = 4, [int]$Lote = 250000, [switch]$Trocar, [switch]$SoValidar, [string]$Origem = 'vetorial.prodes_desmatamento', [string]$SufixoAntiga = 'malha_antiga')

$ErrorActionPreference = 'Stop'
function Psql($sql, [switch]$Silencioso) {
    $ErrorActionPreference = 'Continue'   # NOTICE do psql vem pelo stderr: nao e erro; so o codigo de saida importa
    $r = $sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1 -A -t -F '|' 2>&1 | ForEach-Object { "$_" }
    $codigo = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($codigo -ne 0) { throw "psql falhou: $($r -join ' ')" }
    $r | Where-Object { $_ -notmatch '^(NOTICE|INSERT|CREATE|ALTER|ANALYZE|DROP|GRANT|BEGIN|COMMIT)' -and $_.Trim() }
}
function Log($m) { Write-Host ("[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m) }

if (-not $SoValidar -and -not $Trocar) {
    if ((Psql "SELECT to_regclass('resultados.prodes_municipio_nova') IS NOT NULL;") -eq 't') {
        throw "resultados.prodes_municipio_nova ja existe: confira (pode ser uma execucao interrompida) e rode -SoValidar ou apague a mao antes de refazer."
    }
    Log "malha em dim.municipios (ano_malha x quantidade): $((Psql 'SELECT coalesce(ano_malha::text, ''?'') || '' x '' || count(*) FROM dim.municipios GROUP BY ano_malha ORDER BY 1;') -join '; ')"
    Psql @"
CREATE TABLE resultados.prodes_municipio_nova (
    id           bigserial PRIMARY KEY,
    id_prodes    bigint NOT NULL,
    id_municipio integer NOT NULL,
    calculado_em date NOT NULL DEFAULT CURRENT_DATE
);
ALTER TABLE resultados.prodes_municipio_nova RENAME CONSTRAINT prodes_municipio_nova_pkey TO prodes_municipio_pkey_nova;
CREATE UNIQUE INDEX uq_prodes_municipio_nova ON resultados.prodes_municipio_nova (id_prodes, id_municipio);
"@ | Out-Null
    Log "tabela _nova criada (com indice unico, sem FKs ate o fim da carga)"

    $lotes = Psql @"
SELECT bioma, min(id), max(id), count(*) FROM (
    SELECT bioma, id, (row_number() OVER (PARTITION BY bioma ORDER BY id) - 1) / $Lote AS lote FROM $Origem WHERE vigente_ate IS NULL
) t GROUP BY bioma, lote ORDER BY count(*) DESC, bioma, lote;
"@
    $lista = @($lotes | ForEach-Object { $p = $_ -split '\|'; [pscustomobject]@{ Bioma = $p[0]; Min = [long]$p[1]; Max = [long]$p[2]; N = [long]$p[3] } })
    Log "$($lista.Count) lotes de ate $Lote poligonos, $Paralelo em paralelo"

    $bloco = {
        param($b, $tentativas, $origem)
        $sql = "INSERT INTO resultados.prodes_municipio_nova (id_prodes, id_municipio) SELECT p.id, m.id_municipio FROM $origem p JOIN dim.municipios m ON ST_Intersects(p.geom, m.geom) WHERE p.vigente_ate IS NULL AND p.bioma = '$($b.Bioma)' AND p.id BETWEEN $($b.Min) AND $($b.Max) ON CONFLICT DO NOTHING;"
        for ($t = 1; $t -le $tentativas; $t++) {
            $t0 = Get-Date
            $r = $sql | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1 -At 2>&1
            if ($LASTEXITCODE -eq 0) { return [pscustomobject]@{ Ok = $true; Bioma = $b.Bioma; Min = $b.Min; Max = $b.Max; N = $b.N; Seg = [int]((Get-Date) - $t0).TotalSeconds; Msg = ($r -join ' ') } }
            Start-Sleep 20
        }
        return [pscustomobject]@{ Ok = $false; Bioma = $b.Bioma; Min = $b.Min; Max = $b.Max; N = $b.N; Seg = 0; Msg = ($r -join ' ') }
    }
    $pendentes = New-Object System.Collections.Queue; $lista | ForEach-Object { $pendentes.Enqueue($_) }
    $ativos = @(); $feitos = 0; $falhas = @(); $t0 = Get-Date
    while ($pendentes.Count -gt 0 -or $ativos.Count -gt 0) {
        while ($pendentes.Count -gt 0 -and $ativos.Count -lt $Paralelo) { $ativos += Start-Job -ScriptBlock $bloco -ArgumentList $pendentes.Dequeue(), 2, $Origem }
        $pronto = Wait-Job -Job $ativos -Any
        $res = Receive-Job $pronto; Remove-Job $pronto
        $ativos = @($ativos | Where-Object { $_.Id -ne $pronto.Id })
        $feitos++
        if ($res.Ok) { Log ("lote {0}/{1} ok: {2} {3}-{4} ({5} poligonos, {6} s)" -f $feitos, $lista.Count, $res.Bioma, $res.Min, $res.Max, $res.N, $res.Seg) }
        else { $falhas += $res; Log "lote FALHOU: $($res.Bioma) $($res.Min)-$($res.Max): $($res.Msg)" }
    }
    Log ("carga terminou em {0:N1} min; lotes com falha: {1}" -f ((Get-Date) - $t0).TotalMinutes, $falhas.Count)
    if ($falhas.Count) { throw "$($falhas.Count) lote(s) falharam; rode de novo com -SoValidar apos refazer os lotes a mao, ou apague a tabela _nova e recomece." }

    Log "fechando: indice por municipio, chaves estrangeiras, ANALYZE"
    Psql @"
CREATE INDEX idx_prodes_municipio_id_municipio_nova ON resultados.prodes_municipio_nova (id_municipio);
ALTER TABLE resultados.prodes_municipio_nova ADD CONSTRAINT fk_prodes_municipio_prodes_nova FOREIGN KEY (id_prodes) REFERENCES $Origem (id);
ALTER TABLE resultados.prodes_municipio_nova ADD CONSTRAINT fk_prodes_municipio_municipio_nova FOREIGN KEY (id_municipio) REFERENCES dim.municipios (id_municipio);
ANALYZE resultados.prodes_municipio_nova;
"@ | Out-Null
}

if (-not $Trocar) {
    Log "=== VALIDACAO: nova x atual"
    Psql @"
SELECT 'atual' AS tabela, count(*) AS pares, count(DISTINCT id_prodes) AS poligonos, count(DISTINCT id_municipio) AS municipios FROM resultados.prodes_municipio
UNION ALL SELECT 'nova', count(*), count(DISTINCT id_prodes), count(DISTINCT id_municipio) FROM resultados.prodes_municipio_nova;
SELECT 'poligonos PRODES vigentes (origem)', count(*)::text FROM $Origem WHERE vigente_ate IS NULL
UNION ALL SELECT 'poligonos vigentes sem nenhum municipio (nova)', count(*)::text FROM $Origem p WHERE p.vigente_ate IS NULL AND NOT EXISTS (SELECT 1 FROM resultados.prodes_municipio_nova b WHERE b.id_prodes = p.id)
UNION ALL SELECT 'pares so na nova (por bioma + uuid + municipio)', count(*)::text FROM (
    SELECT p.bioma, p.uuid, n.id_municipio FROM resultados.prodes_municipio_nova n JOIN $Origem p ON p.id = n.id_prodes
    EXCEPT SELECT p.bioma, p.uuid, a.id_municipio FROM resultados.prodes_municipio a JOIN vetorial.prodes_desmatamento p ON p.id = a.id_prodes) x
UNION ALL SELECT 'pares so na atual (por bioma + uuid + municipio)', count(*)::text FROM (
    SELECT p.bioma, p.uuid, a.id_municipio FROM resultados.prodes_municipio a JOIN vetorial.prodes_desmatamento p ON p.id = a.id_prodes
    EXCEPT SELECT p.bioma, p.uuid, n.id_municipio FROM resultados.prodes_municipio_nova n JOIN $Origem p ON p.id = n.id_prodes) y;
"@ | ForEach-Object { Write-Host "  $_" }
    Log "municipios com maior variacao de pares (nova - atual):"
    Psql @"
WITH a AS (SELECT id_municipio, count(*) n FROM resultados.prodes_municipio GROUP BY 1), b AS (SELECT id_municipio, count(*) n FROM resultados.prodes_municipio_nova GROUP BY 1)
SELECT m.nome_municipio || '/' || m.sigla_uf, coalesce(a.n, 0), coalesce(b.n, 0), coalesce(b.n, 0) - coalesce(a.n, 0) FROM dim.municipios m LEFT JOIN a USING (id_municipio) LEFT JOIN b USING (id_municipio)
WHERE coalesce(a.n, 0) <> coalesce(b.n, 0) ORDER BY abs(coalesce(b.n, 0) - coalesce(a.n, 0)) DESC LIMIT 10;
"@ | ForEach-Object { Write-Host "  $_" }
    Log "validacao pronta. Para trocar: .\analises\ponte_prodes_municipio\scripts\refazer_ponte_municipio.ps1 -Trocar"
    return
}

# --- troca (so com -Trocar) ---------------------------------------------------
Log "TROCA: a atual vira prodes_municipio_${SufixoAntiga} (nao e apagada); a nova assume o nome; a view e recriada"
Psql @"
BEGIN;
DROP VIEW IF EXISTS vetorial.v_prodes_municipio;
ALTER TABLE resultados.prodes_municipio RENAME TO prodes_municipio_${SufixoAntiga};
ALTER TABLE resultados.prodes_municipio_${SufixoAntiga} RENAME CONSTRAINT prodes_municipio_pkey TO prodes_municipio_${SufixoAntiga}_pkey;
ALTER INDEX resultados.uq_prodes_municipio RENAME TO uq_prodes_municipio_${SufixoAntiga};
ALTER INDEX resultados.idx_prodes_municipio_id_municipio RENAME TO idx_prodes_municipio_id_municipio_${SufixoAntiga};
ALTER TABLE resultados.prodes_municipio_${SufixoAntiga} RENAME CONSTRAINT fk_prodes_municipio_prodes TO fk_prodes_municipio_prodes_${SufixoAntiga};
ALTER TABLE resultados.prodes_municipio_${SufixoAntiga} RENAME CONSTRAINT fk_prodes_municipio_municipio TO fk_prodes_municipio_municipio_${SufixoAntiga};
ALTER SEQUENCE resultados.prodes_municipio_id_seq RENAME TO prodes_municipio_${SufixoAntiga}_id_seq;

ALTER TABLE resultados.prodes_municipio_nova RENAME TO prodes_municipio;
ALTER TABLE resultados.prodes_municipio RENAME CONSTRAINT prodes_municipio_pkey_nova TO prodes_municipio_pkey;
ALTER INDEX resultados.uq_prodes_municipio_nova RENAME TO uq_prodes_municipio;
ALTER INDEX resultados.idx_prodes_municipio_id_municipio_nova RENAME TO idx_prodes_municipio_id_municipio;
ALTER TABLE resultados.prodes_municipio RENAME CONSTRAINT fk_prodes_municipio_prodes_nova TO fk_prodes_municipio_prodes;
ALTER TABLE resultados.prodes_municipio RENAME CONSTRAINT fk_prodes_municipio_municipio_nova TO fk_prodes_municipio_municipio;
ALTER SEQUENCE resultados.prodes_municipio_nova_id_seq RENAME TO prodes_municipio_id_seq;
GRANT SELECT ON resultados.prodes_municipio TO leitura, geoserver, analistas;

CREATE VIEW vetorial.v_prodes_municipio AS
SELECT b.id AS id_ponte, b.id_municipio, p.id AS id_prodes, p.year, p.main_class, p.class_name, p.area_km, p.image_date,
       p.id_bioma, p.id_estado, p.geom
FROM resultados.prodes_municipio b
JOIN vetorial.prodes_desmatamento p ON p.id = b.id_prodes AND p.vigente_ate IS NULL;
GRANT SELECT ON vetorial.v_prodes_municipio TO leitura, geoserver, analistas;
COMMIT;
"@ | Out-Null
Log "troca feita. Conferencia:"
Psql @"
SELECT 'prodes_municipio (nova, em uso)', count(*)::text FROM resultados.prodes_municipio
UNION ALL SELECT 'prodes_municipio_${SufixoAntiga} (guardada)', count(*)::text FROM resultados.prodes_municipio_${SufixoAntiga}
UNION ALL SELECT 'v_prodes_municipio', count(*)::text FROM vetorial.v_prodes_municipio
UNION ALL SELECT 'geoserver le a view', has_table_privilege('geoserver', 'vetorial.v_prodes_municipio', 'SELECT')::text;
"@ | ForEach-Object { Write-Host "  $_" }
