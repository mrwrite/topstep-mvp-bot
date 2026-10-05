[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$OutputDirectory = "dist/local-executor"
)

$ErrorActionPreference = "Stop"
if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The mutation-capable executor must be built on Windows."
}

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ResolvedOutput = Join-Path $RepositoryRoot $OutputDirectory
$BuildDirectory = Join-Path $RepositoryRoot "build/local-executor"
$env:PYTHONHASHSEED = "0"
$env:SOURCE_DATE_EPOCH = "1767225600"

& $Python -m pip install --disable-pip-version-check -r (Join-Path $RepositoryRoot "local_executor/requirements.lock")
if ($LASTEXITCODE -ne 0) { throw "Runtime dependency installation failed." }
& $Python -m pip install -r (Join-Path $RepositoryRoot "local_executor/requirements-build.lock")
if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed." }

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --workpath $BuildDirectory `
    --distpath $ResolvedOutput `
    (Join-Path $RepositoryRoot "local_executor/windows_executor.spec")
if ($LASTEXITCODE -ne 0) { throw "Executor build failed." }

$Artifact = Join-Path $ResolvedOutput "topstep-local-executor.exe"
if (-not (Test-Path -LiteralPath $Artifact)) { throw "Expected executor artifact was not produced." }

$Installer = $null
$InnoCompiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($null -ne $InnoCompiler) {
    & $InnoCompiler.Source (Join-Path $RepositoryRoot "local_executor/windows_installer.iss")
    if ($LASTEXITCODE -ne 0) { throw "Windows installer build failed." }
    $Installer = Join-Path $ResolvedOutput "Topstep-Local-Executor-Setup.exe"
    if (-not (Test-Path -LiteralPath $Installer)) { throw "Expected installer was not produced." }
}

$HashTarget = if ($null -ne $Installer) { $Installer } else { $Artifact }
$Hash = (Get-FileHash -LiteralPath $HashTarget -Algorithm SHA256).Hash.ToLowerInvariant()
[ordered]@{ artifact = $HashTarget; executable = $Artifact; sha256 = $Hash } | ConvertTo-Json
