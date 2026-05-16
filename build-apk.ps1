<#
.SYNOPSIS
    Builds the Job App Tool Android APK.
.DESCRIPTION
    Checks for JDK 17 and Android SDK, installs if missing, then builds the release APK.
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AndroidDir = Join-Path $ScriptDir "android"

# --- JDK 17 ---
$java = Get-Command "java" -ErrorAction SilentlyContinue
if (-not $java) {
    Write-Host "JDK 17 not found. Installing via winget..." -ForegroundColor Yellow
    winget install EclipseAdoptium.Temurin.17.JDK --accept-package-agreements --accept-source-agreements
    $env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot"
} else {
    Write-Host "JDK found: $($java.Source)" -ForegroundColor Green
}

# --- Android SDK ---
$androidSdk = $env:ANDROID_HOME
if (-not $androidSdk) {
    $androidSdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"
}
if (-not (Test-Path $androidSdk)) {
    Write-Host "Android SDK not found at $androidSdk. Installing..." -ForegroundColor Yellow
    $cmdlineTools = Join-Path $androidSdk "cmdline-tools\latest\bin"
    New-Item -ItemType Directory -Force -Path $cmdlineTools | Out-Null
    
    $sdkZip = Join-Path $env:TEMP "commandlinetools-win.zip"
    Write-Host "Downloading Android command-line tools..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://dl.google.com/android/repository/commandlinetools-win-latest.zip" -OutFile $sdkZip
    
    Write-Host "Extracting..." -ForegroundColor Yellow
    Expand-Archive -Path $sdkZip -DestinationPath "$androidSdk\tmp" -Force
    Move-Item -Path "$androidSdk\tmp\cmdline-tools\*" -Destination $cmdlineTools -Force
    Remove-Item -Path "$androidSdk\tmp" -Recurse -Force -ErrorAction SilentlyContinue
    
    Write-Host "Accepting licenses..." -ForegroundColor Yellow
    & "$cmdlineTools\sdkmanager.bat" --licenses | Out-Null
    & "$cmdlineTools\sdkmanager.bat" "platforms;android-35" "build-tools;35.0.0"
} else {
    Write-Host "Android SDK found at $androidSdk" -ForegroundColor Green
}

$env:ANDROID_HOME = $androidSdk

# Create local.properties
$localProps = Join-Path $AndroidDir "local.properties"
"sdK.dir=$($androidSdk.Replace('\','\\'))" | Set-Content -Path $localProps

# --- Build ---
Write-Host "`nBuilding APK..." -ForegroundColor Cyan
Push-Location $AndroidDir
try {
    # Generate Gradle wrapper if needed
    if (-not (Test-Path "gradlew.bat")) {
        & "$java.Source" -jar (Join-Path $AndroidDir "gradle\wrapper\gradle-wrapper.jar") 2>$null
    }
    
    # Build
    .\gradlew.bat assembleRelease --no-daemon
    
    $apk = Get-ChildItem -Path "app\build\outputs\apk\release\*.apk" -ErrorAction SilentlyContinue
    if ($apk) {
        Write-Host "`nAPK built successfully:" -ForegroundColor Green
        Write-Host "  $($apk.FullName)" -ForegroundColor Green
    } else {
        Write-Host "`nBuild completed but APK not found." -ForegroundColor Red
    }
} finally {
    Pop-Location
}
