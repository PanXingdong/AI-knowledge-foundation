param(
    [string]$RawDir,
    [string]$ManifestPath,
    [string]$OutputPath,
    [switch]$WriteDraft,
    [switch]$Apply,
    [switch]$Strict
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($RawDir)) {
    $RawDir = Join-Path $ProjectRoot "samples\raw"
}
if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path $ProjectRoot "samples\sample-manifest.csv"
}
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $ProjectRoot "samples\sample-manifest.draft.csv"
}

function New-TextFromCodePoints {
    param([int[]]$CodePoints)

    return -join ($CodePoints | ForEach-Object { [char]$_ })
}

$PlaceholderTerms = @(
    (New-TextFromCodePoints @(0x5F85, 0x63D0, 0x4F9B)),
    (New-TextFromCodePoints @(0x5F85, 0x586B, 0x5199)),
    (New-TextFromCodePoints @(0x5F85, 0x786E, 0x8BA4)),
    "TBD",
    "TODO",
    "N/A"
)

function Test-Placeholder {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $true
    }

    $trimmed = $Value.Trim()
    foreach ($term in $PlaceholderTerms) {
        if ($trimmed -eq $term) {
            return $true
        }
    }

    return $false
}

function Resolve-ProjectPath {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $null
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }

    return Join-Path $ProjectRoot $Value
}

function Get-RelativeProjectPath {
    param([string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $rootPath = [System.IO.Path]::GetFullPath($ProjectRoot)
    $prefix = $rootPath.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar

    if ($fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $fullPath.Substring($prefix.Length)
    }

    return $fullPath
}

function New-ManifestRow {
    param([pscustomobject]$Source)

    return [pscustomobject]@{
        sample_id = $Source.sample_id
        slot_type = $Source.slot_type
        file_path = $Source.file_path
        document_title = $Source.document_title
        document_version = $Source.document_version
        owner = $Source.owner
        is_scanned = $Source.is_scanned
        has_tables = $Source.has_tables
        has_multicolumn = $Source.has_multicolumn
        confidentiality = $Source.confidentiality
        status = $Source.status
        notes = $Source.notes
    }
}

if (-not (Test-Path -LiteralPath $ManifestPath)) {
    Write-Error "Manifest not found: $ManifestPath"
}
if (-not (Test-Path -LiteralPath $RawDir)) {
    Write-Error "Raw sample directory not found: $RawDir"
}

$manifestRows = @(Import-Csv -LiteralPath $ManifestPath -Encoding UTF8 | ForEach-Object { New-ManifestRow $_ })
$supportedExtensions = @(".pdf", ".docx", ".doc", ".html", ".htm")
$docs = @(Get-ChildItem -LiteralPath $RawDir -File -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $supportedExtensions -contains $_.Extension.ToLowerInvariant() } |
    Sort-Object FullName)

$existingPaths = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)
foreach ($row in $manifestRows) {
    if (-not (Test-Placeholder $row.file_path)) {
        $resolved = Resolve-ProjectPath $row.file_path
        if ($null -ne $resolved) {
            [void]$existingPaths.Add([System.IO.Path]::GetFullPath($resolved))
        }
    }
}

$candidateDocs = @($docs | Where-Object { -not $existingPaths.Contains([System.IO.Path]::GetFullPath($_.FullName)) })
$docIndex = 0
$filledCount = 0

foreach ($row in $manifestRows) {
    if ((Test-Placeholder $row.file_path) -and $docIndex -lt $candidateDocs.Count) {
        $doc = $candidateDocs[$docIndex]
        $relativePath = Get-RelativeProjectPath $doc.FullName
        $title = [System.IO.Path]::GetFileNameWithoutExtension($doc.Name)

        $row.file_path = $relativePath
        if (Test-Placeholder $row.document_title) {
            $row.document_title = $title
        }
        if (Test-Placeholder $row.status) {
            $row.status = "candidate"
        }
        if (Test-Placeholder $row.notes) {
            $row.notes = "auto-discovered; verify slot_type/version/owner/features"
        }

        $docIndex++
        $filledCount++
    }
}

$extraDocs = @()
if ($docIndex -lt $candidateDocs.Count) {
    $extraDocs = @($candidateDocs[$docIndex..($candidateDocs.Count - 1)])
}

Write-Host "Sample document import"
Write-Host "Project root: $ProjectRoot"
Write-Host "Raw dir: $RawDir"
Write-Host "Manifest: $ManifestPath"
Write-Host "Supported docs found: $($docs.Count)"
Write-Host "New candidate docs: $($candidateDocs.Count)"
Write-Host "Manifest rows filled in draft: $filledCount"
Write-Host "Extra docs beyond manifest slots: $($extraDocs.Count)"

if ($extraDocs.Count -gt 0) {
    Write-Host ""
    Write-Host "Extra docs:"
    $extraDocs | ForEach-Object { Write-Host ("- " + (Get-RelativeProjectPath $_.FullName)) }
}

if ($Strict -and $docs.Count -lt 10) {
    Write-Error "Strict mode requires at least 10 supported sample documents; found $($docs.Count)."
}

if ($WriteDraft -or $Apply) {
    $targetPath = if ($Apply) { $ManifestPath } else { $OutputPath }
    $targetDir = Split-Path -Parent $targetPath
    if (-not [string]::IsNullOrWhiteSpace($targetDir) -and -not (Test-Path -LiteralPath $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }

    if ($Apply) {
        $backupPath = Join-Path (Split-Path -Parent $ManifestPath) ("sample-manifest.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".csv")
        Copy-Item -LiteralPath $ManifestPath -Destination $backupPath
        Write-Host "Backup written: $backupPath"
    }

    $manifestRows | Export-Csv -LiteralPath $targetPath -Encoding UTF8 -NoTypeInformation
    Write-Host "Manifest written: $targetPath"
}
else {
    Write-Host "Dry run only. Use -WriteDraft to write a draft, or -Apply to update the manifest with a backup."
}

exit 0
