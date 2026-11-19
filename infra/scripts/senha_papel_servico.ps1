# Define a senha de um papel de SERVICO do banco (conta de maquina) e a guarda em infra\.env.
#
# Mesmo metodo de criar_papel_etl.ps1, para qualquer papel de servico: a senha e gerada aleatoriamente aqui, nunca impressa, nunca passada
# pela linha de comando e nunca vista por uma pessoa. So o .env e o banco a conhecem. Idempotente: se a variavel ja estiver no .env,
# reaplica o MESMO valor no banco; para trocar, apague a linha do .env e rode de novo.
#
#   .\infra\scripts\senha_papel_servico.ps1 -Papel consulta_ia -Variavel CONSULTA_IA_PASSWORD
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z_][a-z0-9_]*$')][string]$Papel,
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Z_][A-Z0-9_]*$')][string]$Variavel
)
$ErrorActionPreference = 'Stop'
if ($Papel -in @('postgres', 'etl')) { throw "use criar_papel_etl.ps1 para o etl; o postgres nao e papel de servico" }
$infra = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $infra '.env'
if (-not (Test-Path $envFile)) { throw "nao achei $envFile" }

$existe = docker exec dw-postgis psql -U postgres -At -c "SELECT count(*) FROM pg_roles WHERE rolname = '$Papel' AND rolcanlogin"
if ($existe -ne '1') { throw "o papel $Papel nao existe (ou nao tem LOGIN): crie-o antes pelo SQL do servico" }

$linha = Select-String -Path $envFile -Pattern "^\s*$Variavel\s*=" | Select-Object -First 1
if ($linha) {
    $senha = ($linha.Line -split '=', 2)[1].Trim().Trim('"').Trim("'")
    if (-not $senha) { throw "$Variavel esta vazio no .env: apague a linha e rode de novo" }
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
    [System.IO.File]::AppendAllText($envFile, "$prefixo# Senha do papel '$Papel' (servico), gerada por infra/scripts/senha_papel_servico.ps1`r`n$Variavel=$senha`r`n")
    $origem = 'gerada e gravada no .env'
}

# aplica no banco pela entrada padrao (a senha, so de letras e numeros, nao aparece em argumentos)
"ALTER ROLE $Papel PASSWORD '$senha';" | docker exec -i dw-postgis psql -U postgres -d data_warehouse -v ON_ERROR_STOP=1 -q
if ($LASTEXITCODE -ne 0) { throw "falha ao definir a senha no banco" }
$senha = $null
Write-Host "Papel ${Papel}: senha $origem; aplicada no banco (valor nao exibido)." -ForegroundColor Green
