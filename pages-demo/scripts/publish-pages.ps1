param([string]$Repository='bisheshkhanal036-afk/FloodHUBnepal')
$ErrorActionPreference='Stop'
if($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'){throw 'Expected owner/repository'}
$demoRoot=Split-Path $PSScriptRoot -Parent
Set-Location $demoRoot
function Check([string]$Step){if($LASTEXITCODE -ne 0){throw "$Step failed ($LASTEXITCODE)"}}
$repoName=$Repository.Split('/')[1]
$basePath=if($repoName -ieq ($Repository.Split('/')[0]+'.github.io')){'/'}else{"/$repoName/"}
& npm.cmd ci
Check 'Install dependencies'
& npm.cmd test
Check 'Unit/component tests'
& npm.cmd run build -- --base $basePath
Check 'Static build'

# A fresh temporary checkout publishes only generated site files. No user tree is cleared.
$publishDirectory=Join-Path ([IO.Path]::GetTempPath()) ('khola-pages-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $publishDirectory | Out-Null
& git ls-remote --exit-code --heads "https://github.com/$Repository.git" gh-pages | Out-Null
if($LASTEXITCODE -eq 0){
    & git clone --single-branch --branch gh-pages --depth 1 "https://github.com/$Repository.git" $publishDirectory
    Check 'Checkout publishing branch'
}else{
    & git -C $publishDirectory init --initial-branch=gh-pages
    Check 'Initialize publishing branch'
    & git -C $publishDirectory remote add origin "https://github.com/$Repository.git"
    Check 'Set publishing repository'
}
Get-ChildItem -LiteralPath (Join-Path $demoRoot 'dist') -Force | ForEach-Object {Copy-Item -LiteralPath $_.FullName -Destination $publishDirectory -Recurse -Force}
[IO.File]::WriteAllText((Join-Path $publishDirectory '.nojekyll'),'')
& git -C $publishDirectory add --all
Check 'Stage generated website'
& git -C $publishDirectory diff --cached --quiet
if($LASTEXITCODE -ne 0){
    & git -C $publishDirectory commit -m 'Publish Khola static research demo'
    Check 'Commit generated website'
    & git -C $publishDirectory push origin HEAD:gh-pages
    Check 'Push publishing branch'
}
& gh api "repos/$Repository/pages" --silent 2>$null
if($LASTEXITCODE -ne 0){
    & gh api --method POST "repos/$Repository/pages" -f 'source[branch]=gh-pages' -f 'source[path]=/'
    Check 'Enable GitHub Pages'
}else{
    & gh api --method PUT "repos/$Repository/pages" -f 'source[branch]=gh-pages' -f 'source[path]=/'
    Check 'Configure GitHub Pages publishing branch'
}
Write-Output "Publishing requested: https://$($Repository.Split('/')[0]).github.io$basePath"
Write-Output "Generated checkout: $publishDirectory"
