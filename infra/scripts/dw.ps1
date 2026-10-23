# Comandos fixos do data warehouse (um ponto de entrada estavel para o dia a dia).
#
# Uso (PowerShell, a partir de qualquer pasta):
#   .\infra\scripts\dw.ps1 consulta -Sql "select count(*) from vetorial.sicar_imoveis"   # SOMENTE LEITURA (sessao read-only)
#   .\infra\scripts\dw.ps1 psql -Sql "create table ..."                                  # SQL que escreve, como postgres
#   .\infra\scripts\dw.ps1 psql -Arquivo caminho\arquivo.sql                              # SQL de arquivo (acentos, varias linhas)
#   .\infra\scripts\dw.ps1 psql -Papel etl -Sql "..."                                     # outro papel (padrao: postgres)
#   .\infra\scripts\dw.ps1 etl mapbiomas/alerta/scripts/mapbiomas_alerta.py --simular     # pipeline no conteiner etl
#   .\infra\scripts\dw.ps1 backup pos-carga                                               # backup com etiqueta (backup_banco.ps1)
#   .\infra\scripts\dw.ps1 sync-drive [-Simular]                                          # D: -> Drive (so codigo e documentacao)
#   .\infra\scripts\dw.ps1 status                                                         # conteineres e ultimas cargas
#
# Por que existe: aspas embutidas, NOTICE do psql no stderr (que o PowerShell 5.1 trata como erro) e caminhos do Git Bash
# davam tentativa e erro. Aqui cada comando e fixo e a senha nunca passa pela linha de comando (o psql roda dentro do conteiner).
# O codigo de saida e o do comando executado.
param(
    [Parameter(Position = 0, Mandatory = $true)][ValidateSet("consulta", "psql", "etl", "backup", "sync-drive", "status")][string]$Comando,
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Resto,
    [string]$Sql,
    [string]$Arquivo,
    [string]$Papel = "postgres",
    [string]$Banco = "data_warehouse",
    [switch]$Simular
)

$ErrorActionPreference = "Continue"          # NOTICE do psql chega pelo stderr; nao e erro
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$Raiz = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Drive = "G:\Meu Drive\documentos_notebook_pedro\data_warehouse"

function Rodar-Psql([string]$texto, [string[]]$extra, [switch]$SoLeitura) {
    # O SQL vai por ARQUIVO (docker cp + psql -f), nao por pipe: o pipe do PowerShell 5.1 troca letras acentuadas por '?'.
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("dw_cmd_" + [guid]::NewGuid().ToString("N") + ".sql")
    [System.IO.File]::WriteAllText($tmp, $texto, $utf8)
    $remoto = "/tmp/dw_cmd.sql"
    docker cp $tmp "dw-postgis:$remoto" 2>&1 | Out-Null
    Remove-Item -LiteralPath $tmp -Force
    $env_ = if ($SoLeitura) { @("-e", "PGOPTIONS=-c default_transaction_read_only=on") } else { @() }
    $args_ = @("exec") + $env_ + @("dw-postgis", "psql", "-U", $Papel, "-d", $Banco, "-v", "ON_ERROR_STOP=1", "-f", $remoto) + $extra
    & docker @args_ 2>&1 | ForEach-Object { "$_" } | Out-Host   # Out-Host: a saida nao pode virar o valor de retorno
    $codigo = $LASTEXITCODE
    docker exec -u root dw-postgis rm -f $remoto 2>&1 | Out-Null
    return $codigo
}

switch ($Comando) {
    "consulta" {
        # Mesmo que o psql, mas a sessao nasce read-only: INSERT/UPDATE/DDL falham. E o que a lista de permissoes libera sem perguntar.
        if ($Arquivo) { $texto = [System.IO.File]::ReadAllText((Resolve-Path $Arquivo).Path, $utf8) }
        elseif ($Sql) { $texto = $Sql }
        else { Write-Error "consulta exige -Sql ou -Arquivo"; exit 2 }
        $codigo = Rodar-Psql $texto @() -SoLeitura
        exit $codigo
    }
    "psql" {
        if ($Arquivo) { $texto = [System.IO.File]::ReadAllText((Resolve-Path $Arquivo).Path, $utf8) }
        elseif ($Sql) { $texto = $Sql }
        else { Write-Error "psql exige -Sql ou -Arquivo"; exit 2 }
        $codigo = Rodar-Psql $texto @()
        exit $codigo
    }
    "etl" {
        if (-not $Resto) { Write-Error "etl exige o caminho do script (ex.: prodes/desmatamento/scripts/prodes_desmatamento.py)"; exit 2 }
        Push-Location (Join-Path $Raiz "infra")
        try {
            $argumentos = @("compose", "-f", "docker-compose.stack.yml", "-f", "docker-compose.etl.yml", "run", "--rm", "etl") + $Resto
            & docker @argumentos 2>&1 | ForEach-Object { "$_" }
            exit $LASTEXITCODE
        } finally { Pop-Location }
    }
    "backup" {
        $etiqueta = if ($Resto) { $Resto[0] } else { $null }
        if ($etiqueta) { & (Join-Path $Raiz "infra\scripts\backup_banco.ps1") -Etiqueta $etiqueta }
        else { & (Join-Path $Raiz "infra\scripts\backup_banco.ps1") }
        exit $LASTEXITCODE
    }
    "sync-drive" {
        # Copia (nunca apaga no destino) so codigo e documentacao. Fora: dados brutos/processados, segredos, caches, dumps.
        $semPastas = @("bruto", "processado", "__pycache__", ".git", "_dump", "dw_dump", "node_modules", ".venv")
        $semArquivos = @(".env", "*.pyc", "*.gpkg", "*.zip", "*.tif", "*.tiff", "*.shp", "*.dbf", "*.shx", "*.prj", "*.cpg", "*.sbn", "*.sbx",
                         "*.parquet", "*.dump", "*.backup", "*.log")
        $opcoes = @("/E", "/XD") + $semPastas + @("/XF") + $semArquivos + @("/R:1", "/W:1", "/NFL", "/NDL", "/NP", "/NJH")
        if ($Simular) { $opcoes += "/L" }
        if (-not (Test-Path $Drive)) { Write-Error "Drive nao encontrado: $Drive"; exit 2 }
        & robocopy $Raiz $Drive @opcoes 2>&1 | ForEach-Object { "$_" }
        if ($LASTEXITCODE -ge 8) { exit $LASTEXITCODE }   # robocopy: 0 a 7 = sucesso (com ou sem copias)
        if ($Simular) { Write-Output "sync-drive: simulacao, nada copiado" } else { Write-Output "sync-drive concluido" }
        exit 0
    }
    "status" {
        docker ps --format "table {{.Names}}`t{{.Status}}" 2>&1 | ForEach-Object { "$_" }
        $consulta = "select pipeline, status, finalizada_em::timestamp(0) as finalizada from catalogo.cargas order by id desc limit 8"
        $codigo = Rodar-Psql $consulta @() -SoLeitura
        exit $codigo
    }
}
