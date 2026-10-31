param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Atuamax', 'Netflex')]
    [string]$Marca
)

$ErrorActionPreference = 'Stop'
$brandDir = Join-Path $PSScriptRoot $Marca
$exeName = if ($Marca -eq 'Netflex') { 'Personalizador_F6201B_Netflex' } else { 'Personalizador_F6201B' }
$distPath = Join-Path $brandDir 'dist'
$workPath = Join-Path $brandDir 'build'
$archive = Join-Path $brandDir "${Marca}_Windows_x64.zip"

Push-Location $brandDir
try {
    python -m PyInstaller --noconfirm --clean --onedir --windowed `
        --contents-directory . --name $exeName `
        --distpath $distPath --workpath $workPath --specpath $workPath `
        --add-data "$(Join-Path $brandDir 'resources');resources" `
        --add-data "$(Join-Path $brandDir 'resources_n7');resources_n7" `
        --add-data "$(Join-Path $brandDir 'stock_n6');stock_n6" `
        --add-data "$(Join-Path $brandDir 'stock_n7');stock_n7" `
        --add-data "$(Join-Path $brandDir 'brand.json');." `
        --add-data "$(Join-Path $brandDir 'profile.json');." `
        --add-data "$(Join-Path $brandDir 'profile_n7.json');." `
        'Personalizador F6201B.pyw'
    if ($LASTEXITCODE -ne 0) { throw 'A build PyInstaller falhou.' }
    Compress-Archive -LiteralPath (Join-Path $distPath $exeName) -DestinationPath $archive -Force
    Write-Output "Pacote criado: $archive"
}
finally {
    Pop-Location
}
