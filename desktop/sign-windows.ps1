# Sign Windows executables with the code-signing certificate in $env:CERT (a base64 .pfx) and
# $env:PASSWORD, with a timestamp so the signature outlives the certificate. Used by
# .github/workflows/desktop.yml:
#
#     desktop/sign-windows.ps1 dist\QuantumChess\QuantumChess.exe

param([Parameter(Mandatory, ValueFromRemainingArguments)] [string[]] $Files)
$ErrorActionPreference = "Stop"

$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) { throw "signtool.exe not found (Windows SDK)" }

$pfx = Join-Path $env:RUNNER_TEMP "cert.pfx"
[IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:CERT))
try {
    & $signtool.FullName sign /f $pfx /p $env:PASSWORD /fd SHA256 `
        /tr http://timestamp.digicert.com /td SHA256 $Files
    if ($LASTEXITCODE -ne 0) { throw "signing failed" }
    & $signtool.FullName verify /pa $Files
    if ($LASTEXITCODE -ne 0) { throw "the signature does not verify" }
} finally {
    Remove-Item $pfx -ErrorAction SilentlyContinue
}
