# Atualizacao periodica das fontes vivas do data warehouse (decidida em 2026-10-23: a cada 15 dias; ver ROADMAP, item 13).
#
# Roda em sequencia (decidido em 2026-10-23: backup antes e depois):
#   0. BACKUP ANTES (backup_banco.ps1, so local), SALVO se ja existe backup completo de menos de 24 h (reaproveita, ex.: o das 00:10). Se falhar, NADA e atualizado.
#   cada fonte roda no conteiner etl (infra/scripts/dw.ps1 etl ...):
#   1. PRODES        (so baixa e grava o bioma cuja edicao do INPE mudou; os demais sao pulados)
#   2. MapBiomas Alerta
#   2b. FUNAI (terras indigenas, ~10 s)
#   2c. DETER (alertas do INPE, Amazonia e Cerrado, ~8 min na primeira carga; depois so as mudancas)
#   3. SICAR         (as 27 UFs; ~25 min com o PC ligado)
#   4. retencao      (apaga as versoes fechadas alem do prazo de infra/retencao.yaml; trava de 20% por tabela)
#   5. BACKUP DEPOIS (backup_banco.ps1 com copia para o Drive). Como acontece no domingo, o backup agendado das 03:00 (DW-Backup-Domingo-3h)
#      usa -PularSeRecenteHoras 6 e nao duplica. Backups sem etiqueta seguem a retencao (-Manter) do backup_banco.ps1.
# O SIDRA NAO entra: so roda sob demanda, por produto pedido. INCRA (assentamentos e SIGEF) fica de fora enquanto o servidor
# do Acervo Fundiario nao voltar (ROADMAP, item 11).
#
# Uma fonte que falha NAO derruba as outras: o erro vai para catalogo.cargas (status 'falhou') e para o log, e o codigo de saida
# final e 1. O ANALYZE de cada tabela ja roda ao fim de cada pipeline (dwlib.catalogo.Carga). Nao usa --aceitar-queda: se uma
# fonte entregar muito menos do que o banco tem, ela NAO e gravada e fica registrada como falha para voce conferir.
#
# Uso:
#   .\infra\scripts\atualizar_fontes.ps1                 # tudo, de verdade (e o que a tarefa agendada roda)
#   .\infra\scripts\atualizar_fontes.ps1 -Simular        # pipelines com --simular e retencao so em relatorio
#   .\infra\scripts\atualizar_fontes.ps1 -Fontes prodes,mapbiomas   # so algumas (prodes, mapbiomas, funai, deter, ibama, icmbio, sicar, retencao)
# Log: infra\logs\atualizacao_AAAAMMDD-HHMMSS.log
param(
    [string[]]$Fontes = @("prodes", "mapbiomas", "funai", "deter", "ibama", "icmbio", "sicar", "retencao"),
    [switch]$Simular,
    [switch]$SemBackup,         # para testes: nao faz os backups
    [switch]$SemDrive           # para testes: o backup de depois nao copia para o Drive
)

$ErrorActionPreference = "Continue"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$Raiz = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Dw = Join-Path $PSScriptRoot "dw.ps1"
$PastaLog = Join-Path $Raiz "infra\logs"
New-Item -ItemType Directory -Force -Path $PastaLog | Out-Null
$Log = Join-Path $PastaLog ("atualizacao_{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$Trava = Join-Path $PastaLog "atualizar_fontes.lock"
$UFs = "AC,AL,AM,AP,BA,CE,DF,ES,GO,MA,MG,MS,MT,PA,PB,PE,PI,PR,RJ,RN,RO,RR,RS,SC,SE,SP,TO"

function Escrever([string]$texto) {
    $linha = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $texto
    Write-Output $linha
    [System.IO.File]::AppendAllText($Log, $linha + [Environment]::NewLine, $utf8)
}

# evita duas atualizacoes ao mesmo tempo (a trava de uma execucao morta expira em 12 h)
if (Test-Path $Trava) {
    if (((Get-Date) - (Get-Item $Trava).LastWriteTime).TotalHours -lt 12) {
        Escrever "Ja ha uma atualizacao em andamento (trava $Trava). Nada feito."
        exit 3
    }
    Remove-Item -LiteralPath $Trava -Force
}
Set-Content -LiteralPath $Trava -Value $PID

try {
    Escrever ("=== atualizacao das fontes | fontes: {0} | simular: {1} ===" -f ($Fontes -join ","), $Simular.IsPresent)

    # o Docker precisa estar no ar e o banco saudavel
    $estado = docker inspect -f "{{.State.Health.Status}}" dw-postgis 2>$null
    if ($LASTEXITCODE -ne 0 -or $estado -ne "healthy") {
        Escrever "ERRO: dw-postgis nao esta saudavel (estado: '$estado'). Docker Desktop ligado? Abortado."
        exit 2
    }

    $falhas = @()
    function Passo([string]$nome, [string[]]$argumentos) {
        Escrever "--- $nome"
        $inicio = Get-Date
        & $Dw @argumentos 2>&1 | ForEach-Object { Escrever ("    " + $_) }
        $codigo = $LASTEXITCODE
        $min = [math]::Round(((Get-Date) - $inicio).TotalMinutes, 1)
        if ($codigo -ne 0) { Escrever "FALHOU: $nome (codigo $codigo, $min min)"; $script:falhas += $nome }
        else { Escrever "ok: $nome ($min min)" }
    }
    $sim = if ($Simular) { @("--simular") } else { @() }
    $fazerBackup = -not $Simular -and -not $SemBackup
    $Backup = Join-Path $PSScriptRoot "backup_banco.ps1"
    function Fazer-Backup([string]$rotulo, [bool]$drive) {
        Escrever "--- Backup $rotulo"
        $inicio = Get-Date
        $extra = @{ Manter = 6 }                      # hashtable: parametros NOMEADOS (uma lista viraria argumentos posicionais)
        if ($drive) { $extra.CopiarDrive = $true }
        if ($rotulo -eq "antes") { $extra.PularSeRecenteHoras = 24 }   # ja existe backup completo de menos de 24 h (ex.: o de 00:10)? reaproveita
        & $Backup @extra 2>&1 | ForEach-Object { Escrever ("    " + $_) }
        $codigo = $LASTEXITCODE
        $min = [math]::Round(((Get-Date) - $inicio).TotalMinutes, 1)
        # 0 = ok; 2 = backup local ok, so a copia para o Drive falhou (segue, mas avisa)
        if ($codigo -eq 2) { Escrever "AVISO: backup $rotulo local ok, copia para o Drive falhou ($min min)"; $script:falhas += "Backup $rotulo (copia Drive)" }
        elseif ($codigo -ne 0) { Escrever "FALHOU: Backup $rotulo (codigo $codigo, $min min)"; $script:falhas += "Backup $rotulo" }
        else { Escrever "ok: Backup $rotulo ($min min)" }
        $script:codigoBackup = $codigo                # variavel de script: `return` misturaria a saida de Escrever com o codigo
    }

    if ($fazerBackup) {
        Fazer-Backup "antes" $false
        if ($codigoBackup -ne 0 -and $codigoBackup -ne 2) {
            Escrever "=== ABORTADO: sem o backup de antes nada e atualizado. RESULTADO: FALHAS em: $($falhas -join ', ') ==="
            exit 1
        }
    }

    if ($Fontes -contains "prodes")    { Passo "PRODES"            (@("etl", "prodes/desmatamento/scripts/prodes_desmatamento.py") + $sim) }
    if ($Fontes -contains "mapbiomas") { Passo "MapBiomas Alerta" (@("etl", "mapbiomas/alerta/scripts/mapbiomas_alerta.py") + $sim) }
    if ($Fontes -contains "funai")     { Passo "FUNAI (terras indigenas)" (@("etl", "funai/terras_indigenas/scripts/terras_indigenas.py") + $sim) }
    if ($Fontes -contains "deter")     { Passo "DETER (alertas)" (@("etl", "deter/alertas/scripts/deter_alertas.py") + $sim) }
    if ($Fontes -contains "ibama")     { Passo "IBAMA (embargos)" (@("etl", "ibama/embargos/scripts/embargos.py") + $sim) }
    if ($Fontes -contains "icmbio")    { Passo "ICMBio (areas embargadas)" (@("etl", "icmbio/areas_embargadas/scripts/areas_embargadas.py") + $sim) }
    if ($Fontes -contains "sicar")     { Passo "SICAR"             (@("etl", "sicar/imoveis/scripts/atualizar_imoveis_sicar.py", "--ufs", $UFs) + $sim) }
    if ($Fontes -contains "retencao") {
        $apagar = if ($Simular) { @() } else { @("--apagar") }
        Passo "Retencao de versoes fechadas" (@("etl", "infra/scripts/limpar_versoes_fechadas.py") + $apagar)
    }

    if ($fazerBackup) { Fazer-Backup "depois" (-not $SemDrive) }

    Escrever "--- ultimas cargas registradas"
    & $Dw status 2>&1 | ForEach-Object { Escrever ("    " + $_) }
    if ($falhas.Count) { Escrever ("=== RESULTADO: FALHAS em: " + ($falhas -join ", ") + " ==="); exit 1 }
    Escrever "=== RESULTADO: tudo ok ==="
    exit 0
}
finally {
    Remove-Item -LiteralPath $Trava -Force -ErrorAction SilentlyContinue
}
