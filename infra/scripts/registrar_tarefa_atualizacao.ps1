# Registra (ou atualiza) a tarefa agendada do Windows que roda infra\scripts\atualizar_fontes.ps1.
# Decidido em 2026-10-23: domingo as 00:10, a cada 2 semanas (14 dias, o mais proximo de "15 em 15" que cabe num domingo fixo);
# a retencao de 30 dias cobre mais de dois ciclos.
#
# Uso (PowerShell):
#   .\infra\scripts\registrar_tarefa_atualizacao.ps1             # cria/atualiza a tarefa "DW - Atualizacao das fontes"
#   .\infra\scripts\registrar_tarefa_atualizacao.ps1 -Remover    # remove a tarefa
#   .\infra\scripts\registrar_tarefa_atualizacao.ps1 -Primeira "2026-11-01 00:10"   # outra data de inicio
#
# Roda so com o usuario logado (a tela pode estar bloqueada) e com o Docker Desktop ligado; se o PC estiver desligado ou dormindo
# no horario, roda assim que ligar (StartWhenAvailable). Nao precisa de administrador. Para ver o resultado: infra\logs\ e catalogo.cargas.
param(
    [string]$Primeira = "2026-10-25 00:10",
    [switch]$Remover
)
$nome = "DW - Atualizacao das fontes"
if ($Remover) {
    Unregister-ScheduledTask -TaskName $nome -Confirm:$false -ErrorAction SilentlyContinue
    "Tarefa '$nome' removida (se existia)."
    return
}
$script = (Resolve-Path (Join-Path $PSScriptRoot "atualizar_fontes.ps1")).Path
$acao = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$gatilho = New-ScheduledTaskTrigger -Weekly -WeeksInterval 2 -DaysOfWeek Sunday -At ([datetime]$Primeira)
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $config -Principal $principal `
    -Description "Atualiza PRODES, MapBiomas Alerta e SICAR e aplica a retencao de 30 dias (data warehouse GIS). ROADMAP, item 13." -Force | Out-Null
Get-ScheduledTask -TaskName $nome | Get-ScheduledTaskInfo | Select-Object @{n="Tarefa";e={$nome}}, NextRunTime | Format-List
