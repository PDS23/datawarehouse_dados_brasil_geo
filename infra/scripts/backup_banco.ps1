# Backup do banco data_warehouse (stack Docker do desktop).
#
# O que faz: roda pg_dump em formato de diretorio (paralelo) e pg_dumpall
# --globals-only (papeis) a partir de um conteiner descartavel ligado a rede da
# stack, grava numa pasta FORA do volume do banco e FORA de qualquer pasta
# sincronizada (Google Drive/OneDrive), confere o resultado e escreve um
# manifesto. Nao altera o banco. Registra tudo em <Destino>\backup.log.
#
# Senha: lida do infra\.env (POSTGRES_PASSWORD) e passada ao conteiner por
# variavel de ambiente (docker run -e PGPASSWORD, sem o valor na linha de
# comando). Nada e impresso.
#
# Uso (PowerShell, a partir de qualquer pasta):
#   .\infra\scripts\backup_banco.ps1                          (backup simples)
#   .\infra\scripts\backup_banco.ps1 -Manter 4                (agendado: mantem 4)
#   .\infra\scripts\backup_banco.ps1 -Etiqueta pos-carga      (manual, depois de atualizar dados)
#   .\infra\scripts\backup_banco.ps1 -Manter 4 -SoRetencao -Simular   (so mostra o que apagaria)
#
# Nomes: AAAAMMDD-HHMMSS (agendado) e AAAAMMDD-HHMMSS-<etiqueta> (manual).
#
# Retencao: por padrao NAO apaga nada (-Manter 0). Com -Manter N, depois de um
# backup BEM-SUCEDIDO remove os agendados (nome so com data e hora) alem dos N
# mais recentes, so dentro de -Destino. Backups com etiqueta NUNCA sao apagados
# pelo script (apague a mao quando perderem a utilidade). Se o backup falha, a
# retencao nao roda: o ultimo backup bom nunca e apagado por causa de uma falha.
#
# Copia externa (-CopiarDrive): copia dump\ + MANIFESTO.txt para a pasta RESTRITA do Drive
# (G:\Meu Drive\DW_Backups\1_privado_somente_dono) e mantem os 4 agendados mais recentes la
# (-DriveManter). Codigo de saida 2 = backup local OK, copia externa falhou. -SoDrive refaz so a copia.
# O destino principal (-Destino) continua proibido de ser pasta de nuvem.
#
# ATENCAO: globals.sql contem hashes de senha dos papeis. Trate a pasta de
# backup como sensivel: o globals.sql NUNCA vai para o Drive nem para pasta
# compartilhada (a copia externa o deixa de fora de proposito).
#
# Um backup so vale depois de um teste de restauracao: pg_restore -j 4 num banco
# criado de template0/UTF8 e ANALYZE no fim (pg_restore nao roda ANALYZE).
param(
    [string]$Destino = "D:\backups\data_warehouse",
    [int]$Paralelo = 4,
    [int]$Manter = 0,
    [string]$Etiqueta = "",
    [switch]$SoRetencao,
    # >0: se ja existe um backup COMPLETO (com MANIFESTO.txt) de menos de N horas em -Destino, nao faz outro e sai com 0.
    # Usado no backup agendado de domingo para nao duplicar o que atualizar_fontes.ps1 acabou de fazer.
    [int]$PularSeRecenteHoras = 0,
    [switch]$Simular,
    # Copia externa: depois do backup, copia dump\ + MANIFESTO.txt (NUNCA o globals.sql) para a pasta RESTRITA do Drive.
    # -SoDrive: nao faz backup novo, so copia o backup mais recente de -Destino (util para recuperar uma copia que falhou).
    [switch]$CopiarDrive,
    [switch]$SoDrive,
    [string]$DriveDestino = "G:\Meu Drive\DW_Backups\1_privado_somente_dono",
    [int]$DriveManter = 4,
    # exec (padrao): pg_dump DENTRO do dw-postgis pelo socket local (sem senha, sem
    # rede) e docker cp para o destino. rede: conteiner descartavel na rede da
    # stack, entrando como postgres com a senha do .env; so funciona enquanto o
    # pg_hba permitir o postgres pela rede (o pg_hba endurecido nao permite).
    [ValidateSet('exec', 'rede')][string]$Modo = 'exec',
    [string]$Rede = "data-warehouse_default",
    [string]$Imagem = "postgis/postgis:18-3.6"
)

$ErrorActionPreference = 'Stop'
$infra = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $infra '.env'

function Falhar($msg) {
    Write-Host "ERRO: $msg" -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}

function Aplicar-Retencao($pasta, $manter, $simular) {
    if ($manter -le 0) { return }
    $antigos = Get-ChildItem $pasta -Directory |
        Where-Object { $PSItem.Name -match '^\d{8}-\d{6}$' } |
        Sort-Object Name -Descending | Select-Object -Skip $manter
    foreach ($a in $antigos) {
        if (-not $a.FullName.StartsWith($pasta)) { continue }   # nunca fora do destino
        if ($simular) { Write-Host "retencao (simulacao): removeria $($a.FullName)"; continue }
        Write-Host "retencao: removendo $($a.FullName)"
        Remove-Item -LiteralPath $a.FullName -Recurse -Force
    }
    if (-not $antigos) { Write-Host "retencao: nada a remover (mantendo ate $manter agendados)" }
}

# Copia um backup para o Drive (so dump\ e MANIFESTO.txt). Retorna $true se a copia conferiu (mesmos arquivos e bytes).
# Nunca derruba o backup local: quem chama decide o codigo de saida. O Drive para desktop precisa estar aberto (G:).
function Copiar-ParaDrive($origem, $nome, $driveDestino, $manter) {
    $raizDrive = Split-Path -Parent (Split-Path -Parent $driveDestino)        # G:\Meu Drive
    # Ao ligar o PC (backup de recuperacao na segunda de manha) o Drive pode demorar a montar G: : espera ate 5 min.
    for ($i = 0; $i -lt 10 -and -not (Test-Path -LiteralPath $raizDrive); $i++) {
        Write-Host "aguardando o Drive ($raizDrive) ... $($i + 1)/10"
        Start-Sleep -Seconds 30
    }
    if (-not (Test-Path -LiteralPath $raizDrive)) {
        Write-Host "AVISO: Drive indisponivel ($raizDrive): copia externa NAO feita. Rode -SoDrive quando o Drive abrir." -ForegroundColor Yellow
        return $false
    }
    $destino = Join-Path $driveDestino $nome
    New-Item -ItemType Directory -Force $destino | Out-Null
    Write-Host "[$nome] copiando dump\ para o Drive ($destino), sem o globals.sql ..."
    robocopy (Join-Path $origem 'dump') (Join-Path $destino 'dump') /E /R:3 /W:10 /NP /NFL /NDL /NJH | Out-Null
    if ($LASTEXITCODE -ge 8) { Write-Host "AVISO: robocopy falhou (codigo $LASTEXITCODE)" -ForegroundColor Yellow; return $false }
    Copy-Item -LiteralPath (Join-Path $origem 'MANIFESTO.txt') (Join-Path $destino 'MANIFESTO.txt') -Force
    $a = Get-ChildItem (Join-Path $origem 'dump') -File | Measure-Object Length -Sum
    $b = Get-ChildItem (Join-Path $destino 'dump') -File | Measure-Object Length -Sum
    if ($a.Count -ne $b.Count -or $a.Sum -ne $b.Sum) {
        Write-Host "AVISO: copia no Drive NAO confere ($($b.Count) arquivos/$($b.Sum) bytes x origem $($a.Count)/$($a.Sum))" -ForegroundColor Yellow
        return $false
    }
    Write-Host ("[{0}] Drive OK: {1} arquivos, {2:N2} GB" -f $nome, $b.Count, ($b.Sum / 1GB)) -ForegroundColor Green
    # retencao no Drive: so os agendados (nome so com data e hora), alem dos $manter mais recentes; com etiqueta nunca
    if ($manter -gt 0) {
        $antigos = Get-ChildItem $driveDestino -Directory | Where-Object { $PSItem.Name -match '^\d{8}-\d{6}$' } |
            Sort-Object Name -Descending | Select-Object -Skip $manter
        foreach ($a2 in $antigos) {
            if (-not $a2.FullName.StartsWith($driveDestino)) { continue }
            Write-Host "retencao no Drive: removendo $($a2.FullName)"
            Remove-Item -LiteralPath $a2.FullName -Recurse -Force
        }
    }
    return $true
}

# --- destino e log ----------------------------------------------------------
if ($Etiqueta -and $Etiqueta -notmatch '^[A-Za-z0-9\-]{1,30}$') {
    Write-Host "ERRO: -Etiqueta aceita so letras, numeros e hifen (ate 30)" -ForegroundColor Red; exit 1
}
$resolvido = [System.IO.Path]::GetFullPath($Destino)
if ($resolvido -match 'Google Drive|My Drive|Meu Drive|OneDrive|^G:\\') {
    Write-Host "ERRO: o destino parece pasta sincronizada na nuvem ($resolvido): escolha um disco local" -ForegroundColor Red; exit 1
}
New-Item -ItemType Directory -Force $resolvido | Out-Null
Start-Transcript -Path (Join-Path $resolvido 'backup.log') -Append | Out-Null
Write-Host "=== backup_banco.ps1 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | Manter=$Manter Etiqueta='$Etiqueta' SoRetencao=$SoRetencao ==="
if ($PularSeRecenteHoras -gt 0 -and -not $SoRetencao -and -not $SoDrive) {
    $recente = Get-ChildItem $resolvido -Directory -ErrorAction SilentlyContinue |
        Where-Object { $PSItem.Name -match '^\d{8}-\d{6}' -and $PSItem.Name -notmatch '\.parcial$' -and (Test-Path (Join-Path $PSItem.FullName 'MANIFESTO.txt')) -and
                       ((Get-Date) - $PSItem.LastWriteTime).TotalHours -lt $PularSeRecenteHoras } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($recente) {
        Write-Host "Backup pulado: ja existe $($recente.Name) de menos de $PularSeRecenteHoras h (-PularSeRecenteHoras)."
        exit 0
    }
}

if ($SoRetencao) {
    Aplicar-Retencao $resolvido $Manter $Simular
    Stop-Transcript | Out-Null
    exit 0
}

if ($SoDrive) {
    $ultimo = Get-ChildItem $resolvido -Directory | Where-Object { $PSItem.Name -match '^\d{8}-\d{6}' -and $PSItem.Name -notmatch '\.parcial$' } |
        Sort-Object Name -Descending | Select-Object -First 1
    if (-not $ultimo) { Falhar "nenhum backup encontrado em $resolvido" }
    $ok = Copiar-ParaDrive $ultimo.FullName $ultimo.Name $DriveDestino $DriveManter
    Stop-Transcript | Out-Null
    exit $(if ($ok) { 0 } else { 2 })
}

# --- pre-condicoes ----------------------------------------------------------
$saude = docker inspect -f "{{.State.Health.Status}}" dw-postgis 2>$null
if ($saude -ne 'healthy') { Falhar "dw-postgis nao esta healthy (estado: '$saude'); o Docker Desktop esta aberto?" }
if ($Modo -eq 'rede') {
    if (-not (Test-Path $envFile)) { Falhar "nao achei $envFile" }
    $linha = Select-String -Path $envFile -Pattern '^\s*POSTGRES_PASSWORD\s*=' | Select-Object -First 1
    if (-not $linha) { Falhar "POSTGRES_PASSWORD nao esta no .env" }
    $senha = ($linha.Line -split '=', 2)[1].Trim().Trim('"').Trim("'")
    if (-not $senha) { Falhar "POSTGRES_PASSWORD esta vazio no .env" }
    $redes = docker network ls --format "{{.Name}}"
    if ($redes -notcontains $Rede) { Falhar "rede Docker '$Rede' nao existe (docker network ls)" }
}

$carimbo = Get-Date -Format 'yyyyMMdd-HHmmss'
$nome = if ($Etiqueta) { "$carimbo-$Etiqueta" } else { $carimbo }
$parcial = Join-Path $resolvido "$nome.parcial"
$final = Join-Path $resolvido $nome
New-Item -ItemType Directory -Force $parcial | Out-Null

$inicio = Get-Date
if ($Modo -eq 'exec') {
    # Dentro do dw-postgis, pelo socket local (pg_hba: local trust). O dump fica
    # numa pasta temporaria do conteiner (camada gravavel, no disco do Docker) e
    # e copiado para o destino; a pasta temporaria e sempre apagada no fim.
    $tmp = "/tmp/dwbackup_$carimbo"
    try {
        docker exec dw-postgis sh -c "rm -rf $tmp && mkdir -p $tmp"
        if ($LASTEXITCODE -ne 0) { Falhar "nao consegui criar $tmp no conteiner" }

        Write-Host "[$nome] pg_dump -Fd -j $Paralelo (modo exec, socket local) ..."
        docker exec dw-postgis pg_dump -U postgres -d data_warehouse -Fd -j $Paralelo -f "$tmp/dump"
        if ($LASTEXITCODE -ne 0) { Falhar "pg_dump terminou com codigo $LASTEXITCODE (pasta parcial mantida: $parcial)" }

        Write-Host "[$nome] pg_dumpall --globals-only ..."
        docker exec dw-postgis pg_dumpall -U postgres --globals-only -f "$tmp/globals.sql"
        if ($LASTEXITCODE -ne 0) { Falhar "pg_dumpall terminou com codigo $LASTEXITCODE (pasta parcial mantida: $parcial)" }

        Write-Host "[$nome] docker cp para $parcial ..."
        # O destino do dump NAO pode existir: assim o docker cp cria "dump" com o conteudo.
        docker cp "dw-postgis:$tmp/dump" (Join-Path $parcial 'dump')
        if ($LASTEXITCODE -ne 0) { Falhar "docker cp do dump falhou (pasta parcial mantida: $parcial)" }
        docker cp "dw-postgis:$tmp/globals.sql" (Join-Path $parcial 'globals.sql')
        if ($LASTEXITCODE -ne 0) { Falhar "docker cp do globals.sql falhou (pasta parcial mantida: $parcial)" }
    }
    finally {
        docker exec dw-postgis sh -c "rm -rf $tmp" 2>$null | Out-Null
    }
}
else {
    $env:PGPASSWORD = $senha
    try {
        Write-Host "[$nome] pg_dump -Fd -j $Paralelo (modo rede) ..."
        docker run --rm --network $Rede -e PGPASSWORD -v "${parcial}:/out" $Imagem `
            pg_dump -h postgis -U postgres -d data_warehouse -Fd -j $Paralelo -f /out/dump
        if ($LASTEXITCODE -ne 0) { Falhar "pg_dump terminou com codigo $LASTEXITCODE (pasta parcial mantida: $parcial)" }

        Write-Host "[$nome] pg_dumpall --globals-only ..."
        docker run --rm --network $Rede -e PGPASSWORD -v "${parcial}:/out" $Imagem `
            pg_dumpall -h postgis -U postgres --globals-only -f /out/globals.sql
        if ($LASTEXITCODE -ne 0) { Falhar "pg_dumpall terminou com codigo $LASTEXITCODE (pasta parcial mantida: $parcial)" }
    }
    finally {
        $env:PGPASSWORD = $null
    }
}

# --- conferencia ------------------------------------------------------------
# 1) o indice do dump le (toc.dat integro) e traz os dados das tabelas grandes
$lista = docker run --rm -v "${parcial}:/out" $Imagem pg_restore --list /out/dump
if ($LASTEXITCODE -ne 0) { Falhar "pg_restore --list falhou: dump ilegivel (pasta parcial mantida: $parcial)" }
$dados = @($lista | Select-String -CaseSensitive 'TABLE DATA')   # sem -CaseSensitive casa tambem "ACL ... TABLE datasets"
$grandes = 'prodes_desmatamento', 'sicar_imoveis', 'prodes_municipio'
foreach ($g in $grandes) {
    if (-not ($dados | Select-String $g)) { Falhar "dump sem dados de $g (pasta parcial mantida: $parcial)" }
}
# 2) cada .dat.gz e um gzip integro (um arquivo truncado falha aqui)
docker run --rm -v "${parcial}:/out" $Imagem sh -c 'for f in /out/dump/*.dat.gz; do gzip -t "$f" || exit 1; done'
if ($LASTEXITCODE -ne 0) { Falhar "algum .dat.gz esta corrompido ou truncado (pasta parcial mantida: $parcial)" }

# --- fecha o backup ---------------------------------------------------------
$bytes = (Get-ChildItem $parcial -Recurse -File | Measure-Object Length -Sum).Sum
$fim = Get-Date
# Cada -f entre parenteses: sem eles o operador virgula engole as linhas seguintes.
@(
    "backup:      $nome",
    "etiqueta:    $Etiqueta",
    "inicio:      $inicio",
    "fim:         $fim",
    ("duracao_min: {0:N1}" -f (($fim - $inicio).TotalMinutes)),
    ("tamanho_gb:  {0:N2}" -f ($bytes / 1GB)),
    "tabelas_com_dados: $($dados.Count)",
    "modo:        $Modo",
    "imagem:      $Imagem"
) | Set-Content (Join-Path $parcial 'MANIFESTO.txt') -Encoding UTF8
Rename-Item -LiteralPath $parcial -NewName $nome
Write-Host ("[{0}] OK: {1:N2} GB em {2:N1} min -> {3}" -f $nome, ($bytes / 1GB), (($fim - $inicio).TotalMinutes), $final) -ForegroundColor Green

# --- retencao: so depois de um backup bem-sucedido -------------------------
Aplicar-Retencao $resolvido $Manter $Simular

# --- copia externa (Drive): o backup local ja esta salvo; falha aqui da codigo 2, nao 1 ---
$codigo = 0
if ($CopiarDrive) {
    if (-not (Copiar-ParaDrive $final $nome $DriveDestino $DriveManter)) { $codigo = 2 }
}
Stop-Transcript | Out-Null
exit $codigo
