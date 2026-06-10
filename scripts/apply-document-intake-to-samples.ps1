param(
    [string]$DocumentIntakePath,
    [string]$RawDir,
    [string]$ManifestPath,
    [int]$MinimumDocuments = 10,
    [switch]$Apply,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($DocumentIntakePath)) {
    $DocumentIntakePath = Join-Path $ProjectRoot "samples\document-intake-template.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($DocumentIntakePath)) {
    $DocumentIntakePath = Join-Path $ProjectRoot $DocumentIntakePath
}

if ([string]::IsNullOrWhiteSpace($RawDir)) {
    $RawDir = Join-Path $ProjectRoot "samples\raw"
}
elseif (-not [System.IO.Path]::IsPathRooted($RawDir)) {
    $RawDir = Join-Path $ProjectRoot $RawDir
}

if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path $ProjectRoot "samples\sample-manifest.csv"
}
elseif (-not [System.IO.Path]::IsPathRooted($ManifestPath)) {
    $ManifestPath = Join-Path $ProjectRoot $ManifestPath
}

function New-TextFromCodePoints {
    param([int[]]$CodePoints)

    return -join ($CodePoints | ForEach-Object { [char]$_ })
}

$PlaceholderTerms = @(
    (New-TextFromCodePoints @(0x5F85, 0x63D0, 0x4F9B)),
    (New-TextFromCodePoints @(0x5F85, 0x586B, 0x5199)),
    (New-TextFromCodePoints @(0x5F85, 0x786E, 0x8BA4)),
    (New-TextFromCodePoints @(0x5F85, 0x8BC4, 0x5206)),
    (New-TextFromCodePoints @(0x5F85, 0x5B9A)),
    "TBD",
    "TODO",
    "N/A"
)

$AffirmativeTerms = @(
    "1",
    "true",
    "yes",
    "y",
    "selected",
    "select",
    "ok",
    "pass",
    (New-TextFromCodePoints @(0x662F)),
    (New-TextFromCodePoints @(0x6709)),
    (New-TextFromCodePoints @(0x5DF2, 0x9009)),
    (New-TextFromCodePoints @(0x9009, 0x4E2D))
)

$SupportedExtensions = @(".pdf", ".docx", ".doc", ".html", ".htm")

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

function Test-Affirmative {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $false
    }

    $normalized = $Value.Trim().ToLowerInvariant()
    foreach ($term in $AffirmativeTerms) {
        if ($normalized -eq $term.ToLowerInvariant()) {
            return $true
        }
    }

    return $false
}

function Test-ExternalSourceLocation {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $false
    }

    return $Value.Trim() -match '^(https?)://'
}

function Resolve-SourceLocation {
    param([string]$Value)

    if (Test-Placeholder $Value) {
        return $null
    }

    $trimmed = $Value.Trim()
    if ([System.IO.Path]::IsPathRooted($trimmed)) {
        return $trimmed
    }

    return Join-Path $ProjectRoot $trimmed
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

function ConvertTo-SafeFileStem {
    param(
        [string]$Value,
        [string]$Fallback
    )

    $source = if (Test-Placeholder $Value) { $Fallback } else { $Value.Trim() }
    $invalidChars = [System.IO.Path]::GetInvalidFileNameChars()
    foreach ($char in $invalidChars) {
        $source = $source.Replace([string]$char, "-")
    }

    $source = [regex]::Replace($source, "\s+", "-")
    $source = [regex]::Replace($source, "-+", "-").Trim(".-")
    if ([string]::IsNullOrWhiteSpace($source)) {
        return $Fallback
    }

    return $source
}

function Get-MissingFields {
    param(
        [object]$Row,
        [string[]]$Fields
    )

    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($field in $Fields) {
        if (Test-Placeholder $Row.$field) {
            $missing.Add($field) | Out-Null
        }
    }

    return @($missing)
}

function Test-SafeToOverwriteManifest {
    param([string]$Path)

    if ($Force -or -not (Test-Path -LiteralPath $Path)) {
        return $true
    }

    $content = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    foreach ($term in $PlaceholderTerms) {
        if ($content -like "*$term*") {
            return $true
        }
    }

    return $false
}

function Assert-RequiredColumns {
    param(
        [object[]]$Rows,
        [string[]]$RequiredColumns,
        [string]$Name
    )

    if ($Rows.Count -eq 0) {
        Write-Error "$Name has no rows."
    }

    $columns = @($Rows[0].PSObject.Properties.Name)
    $missingColumns = @($RequiredColumns | Where-Object { $_ -notin $columns })
    if ($missingColumns.Count -gt 0) {
        Write-Error "$Name is missing columns: $($missingColumns -join ', ')"
    }
}

if (-not (Test-Path -LiteralPath $DocumentIntakePath)) {
    Write-Error "Document intake file not found: $DocumentIntakePath"
}
if (-not (Test-Path -LiteralPath $ManifestPath)) {
    Write-Error "Sample manifest not found: $ManifestPath"
}

$documentRows = @(Import-Csv -LiteralPath $DocumentIntakePath -Encoding UTF8)
$manifestRows = @(Import-Csv -LiteralPath $ManifestPath -Encoding UTF8)

$requiredDocumentColumns = @(
    "candidate_id",
    "slot_type",
    "source_location",
    "document_title",
    "document_version",
    "owner",
    "is_scanned",
    "has_tables",
    "has_multicolumn",
    "confidentiality",
    "allowed_for_experiment",
    "candidate_reason",
    "notes"
)

$requiredManifestColumns = @(
    "sample_id",
    "slot_type",
    "file_path",
    "document_title",
    "document_version",
    "owner",
    "is_scanned",
    "has_tables",
    "has_multicolumn",
    "confidentiality",
    "status",
    "notes"
)

Assert-RequiredColumns $documentRows $requiredDocumentColumns "Document intake"
Assert-RequiredColumns $manifestRows $requiredManifestColumns "Sample manifest"

if ($manifestRows.Count -lt $MinimumDocuments) {
    Write-Error "Sample manifest needs at least $MinimumDocuments rows; found $($manifestRows.Count)."
}

$readyRows = New-Object System.Collections.Generic.List[object]
$incompleteRows = New-Object System.Collections.Generic.List[string]

foreach ($row in $documentRows) {
    $missing = Get-MissingFields $row @(
        "candidate_id",
        "slot_type",
        "source_location",
        "document_title",
        "document_version",
        "owner",
        "is_scanned",
        "has_tables",
        "has_multicolumn",
        "confidentiality",
        "candidate_reason"
    )

    if (-not (Test-Affirmative $row.allowed_for_experiment)) {
        $missing += "allowed_for_experiment"
    }

    $resolvedSource = $null
    if (-not (Test-Placeholder $row.source_location)) {
        if (Test-ExternalSourceLocation $row.source_location) {
            $missing += "source_location_local_file"
        }
        else {
            $resolvedSource = Resolve-SourceLocation $row.source_location
            if ($null -eq $resolvedSource -or -not (Test-Path -LiteralPath $resolvedSource -PathType Leaf)) {
                $missing += "source_location_exists"
            }
            else {
                $extension = [System.IO.Path]::GetExtension($resolvedSource).ToLowerInvariant()
                if ($SupportedExtensions -notcontains $extension) {
                    $missing += "supported_extension"
                }
            }
        }
    }

    if ($missing.Count -eq 0) {
        $readyRows.Add([pscustomobject]@{
            Intake = $row
            SourcePath = [System.IO.Path]::GetFullPath($resolvedSource)
        }) | Out-Null
    }
    else {
        $candidateId = if (Test-Placeholder $row.candidate_id) { "<missing-candidate-id>" } else { $row.candidate_id }
        $incompleteRows.Add(("{0}: {1}" -f $candidateId, ($missing -join ","))) | Out-Null
    }
}

if ($readyRows.Count -lt $MinimumDocuments) {
    Write-Error "Expected at least $MinimumDocuments ready document candidates, found $($readyRows.Count). Incomplete candidates: $($incompleteRows -join '; ')"
}

$duplicateIds = @(
    $readyRows |
        ForEach-Object { $_.Intake } |
        Group-Object candidate_id |
        Where-Object { $_.Count -gt 1 } |
        ForEach-Object { $_.Name }
)
if ($duplicateIds.Count -gt 0) {
    Write-Error "Duplicate candidate_id values among ready documents: $($duplicateIds -join ', ')"
}

$selectedRows = @($readyRows | Select-Object -First $MinimumDocuments)

if (@($selectedRows | Where-Object { Test-Affirmative $_.Intake.has_tables }).Count -eq 0) {
    Write-Error "Selected document candidates need at least one table document."
}
if (@($selectedRows | Where-Object { Test-Affirmative $_.Intake.has_multicolumn }).Count -eq 0) {
    Write-Error "Selected document candidates need at least one multicolumn document."
}
if (@($selectedRows | Where-Object { Test-Affirmative $_.Intake.is_scanned }).Count -eq 0) {
    Write-Error "Selected document candidates need at least one scanned/OCR-risk document."
}

$plans = New-Object System.Collections.Generic.List[object]
$destinationPaths = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)

for ($i = 0; $i -lt $selectedRows.Count; $i++) {
    $ready = $selectedRows[$i]
    $row = $ready.Intake
    $sourcePath = $ready.SourcePath
    $extension = [System.IO.Path]::GetExtension($sourcePath).ToLowerInvariant()
    $safeStem = ConvertTo-SafeFileStem $row.candidate_id ("sample-{0:000}" -f ($i + 1))
    $destinationPath = Join-Path $RawDir ($safeStem + $extension)
    $destinationFullPath = [System.IO.Path]::GetFullPath($destinationPath)

    if (-not $destinationPaths.Add($destinationFullPath)) {
        Write-Error "Duplicate destination path planned: $destinationFullPath"
    }

    $plans.Add([pscustomobject]@{
        Index = $i
        Intake = $row
        SourcePath = $sourcePath
        DestinationPath = $destinationFullPath
    }) | Out-Null
}

foreach ($plan in $plans) {
    $sourceFull = [System.IO.Path]::GetFullPath($plan.SourcePath)
    $destinationFull = [System.IO.Path]::GetFullPath($plan.DestinationPath)
    if (
        $Apply -and
        (Test-Path -LiteralPath $destinationFull) -and
        -not $Force -and
        -not $sourceFull.Equals($destinationFull, [System.StringComparison]::OrdinalIgnoreCase)
    ) {
        Write-Error "Refusing to overwrite existing sample document without -Force: $destinationFull"
    }
}

if ($Apply -and -not (Test-SafeToOverwriteManifest $ManifestPath)) {
    Write-Error "Refusing to overwrite non-placeholder manifest without -Force: $ManifestPath"
}

for ($i = 0; $i -lt $plans.Count; $i++) {
    $plan = $plans[$i]
    $row = $plan.Intake
    $manifestRow = $manifestRows[$i]
    $notes = "from $($row.candidate_id); $($row.candidate_reason)"
    if (-not (Test-Placeholder $row.notes)) {
        $notes = "$notes; $($row.notes)"
    }

    $manifestRow.slot_type = $row.slot_type
    $manifestRow.file_path = Get-RelativeProjectPath $plan.DestinationPath
    $manifestRow.document_title = $row.document_title
    $manifestRow.document_version = $row.document_version
    $manifestRow.owner = $row.owner
    $manifestRow.is_scanned = $row.is_scanned
    $manifestRow.has_tables = $row.has_tables
    $manifestRow.has_multicolumn = $row.has_multicolumn
    $manifestRow.confidentiality = $row.confidentiality
    $manifestRow.status = "ready"
    $manifestRow.notes = $notes
}

Write-Host "Document intake to sample manifest"
Write-Host "Document intake: $DocumentIntakePath"
Write-Host "Raw dir: $RawDir"
Write-Host "Manifest: $ManifestPath"
Write-Host "Ready document candidates: $($readyRows.Count)"
Write-Host "Selected document candidates: $($selectedRows.Count)"
Write-Host "Mode: $(if ($Apply) { 'apply' } else { 'dry run' })"

if ($incompleteRows.Count -gt 0) {
    Write-Host "Incomplete candidates ignored: $($incompleteRows.Count)"
}
if ($readyRows.Count -gt $MinimumDocuments) {
    Write-Host "Ready candidates beyond first $MinimumDocuments ignored: $($readyRows.Count - $MinimumDocuments)"
}

Write-Host ""
Write-Host "Planned document copies:"
foreach ($plan in $plans) {
    Write-Host ("- {0} -> {1}" -f $plan.SourcePath, $plan.DestinationPath)
}

if ($Apply) {
    if (-not (Test-Path -LiteralPath $RawDir)) {
        New-Item -ItemType Directory -Path $RawDir -Force | Out-Null
    }

    foreach ($plan in $plans) {
        $sourceFull = [System.IO.Path]::GetFullPath($plan.SourcePath)
        $destinationFull = [System.IO.Path]::GetFullPath($plan.DestinationPath)
        if (-not $sourceFull.Equals($destinationFull, [System.StringComparison]::OrdinalIgnoreCase)) {
            Copy-Item -LiteralPath $sourceFull -Destination $destinationFull -Force:$Force
        }
    }

    $backupPath = Join-Path (Split-Path -Parent $ManifestPath) ("sample-manifest.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".csv")
    Copy-Item -LiteralPath $ManifestPath -Destination $backupPath
    $manifestRows | Export-Csv -LiteralPath $ManifestPath -Encoding UTF8 -NoTypeInformation

    Write-Host ""
    Write-Host "Backup written: $backupPath"
    Write-Host "Manifest written: $ManifestPath"
    Write-Host "DOCUMENT_INTAKE_APPLY=PASS"
}
else {
    Write-Host ""
    Write-Host "Dry run only. Use -Apply to copy documents and update the manifest."
    Write-Host "DOCUMENT_INTAKE_DRY_RUN=PASS"
}

exit 0
