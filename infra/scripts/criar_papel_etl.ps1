# Define a senha do papel "etl" do banco e a guarda em infra\.env (ETL_PASSWORD).
#
# A senha e um segredo de MAQUINA (conta de servico): e gerada aleatoriamente aqui, nunca
# impressa, nunca passada pela linha de comando e nunca vista por uma pessoa. So o .env e o
# banco a conhecem. Idempotente: se ETL_PASSWORD ja estiver no .env, reaplica o MESMO valor
# no banco (nao gera outro); para trocar a senha, apague a linha ETL_PASSWORD do .env e rode
# de novo.
#
# Pre-requisito: infra/postgres/etl_base.sql ja executado (cria o papel).
#
#   .\infra\scripts\criar_papel_etl.ps1
$ErrorActionPreference = 'Stop'
$infra = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $infra '.env'
if (-not (Test-Path $envFile)) { throw "nao achei $envFile" }

$existe = docker exec dw-postgis psql -U postgres -At -c "SELECT count(*) FROM pg_roles WHERE rolname = 'etl'"
if ($existe -ne '1') { throw "o papel etl nao existe: rode infra\postgres\etl_base.sql primeiro" }

$linha = Select-String -Path $envFile -Pattern '^\s*ETL_PASSWORD\s*=' | Select-Object -First 1
if ($linha) {
    $senha = ($linha.Line -split '=', 2)[1].Trim().Trim('"').Trim("'")
    if (-not $senha) { throw "ETL_PASSWORD esta vazio no .env: apague a linha e rode de novo" }
    $origem = 'reaplicada a existente'
}
else {
    $bytes = New-Object byte[] 48
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()   # Windows PowerShell 5.1 nao tem ::Fill
    $rng.GetBytes($bytes)
    $rng.Dispose()
    $alfabeto = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    $senha = -join ($bytes[0..31] | ForEach-Object { $alfabeto[$PSItem % $alfabeto.Length] })
    # garante quebra de linha antes de acrescentar (sem ler o conteudo do .env)
    $b = [System.IO.File]::ReadAllBytes($envFile)
    $prefixo = if ($b.Length -gt 0 -and $b[$b.Length - 1] -ne 10) { "`r`n" } else { '' }
    [System.IO.File]::AppendAllText($envFile, "$prefixo# Senha do papel 'etl' (coleta automatizada), gerada por infra/scripts/criar_papel_etl.ps1`r`nETL_PASSWORD=$senha`r`n")
    $origem = 'gerada e gravada no .env'
}

# aplica no banco pela entrada padrao (a senha, so de letras e numeros, nao aparece em argumentos)
"ALTER ROLE etl PASSWORD '$senha';" | docker exec -i dw-postgis psql -U postgres -v ON_ERROR_STOP=1 -q
if ($LASTEXITCODE -ne 0) { throw "falha ao definir a senha no banco" }
$senha = $null
Write-Host "Papel etl: senha $origem; aplicada no banco (valor nao exibido)." -ForegroundColor Green
