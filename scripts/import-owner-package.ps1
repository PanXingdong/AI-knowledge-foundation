param(
    [Parameter(Mandatory = $true)]
    [string]$PackagePath,
    [string]$DocumentIntakePath,
    [string]$TaskIntakePath,
    [string]$IncomingDocsDir,
    [string]$ArtifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts"),
    [string]$Owner,
    [switch]$Apply,
    [switch]$Force,
    [switch]$KeepExtracted
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ImportId = "owner-import-" + (Get-Date -Format "yyyyMMdd-HHmmss")

function Resolve-ProjectPath {
    param(
        [string]$Value,
        [string]$DefaultRelativePath
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return Join-Path $ProjectRoot $DefaultRelativePath
    }

    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }

    return Join-Path $ProjectRoot $Value
}

$PackagePath = Resolve-ProjectPath $PackagePath $null
$DocumentIntakePath = Resolve-ProjectPath $DocumentIntakePath "samples\document-intake-template.csv"
$TaskIntakePath = Resolve-ProjectPath $TaskIntakePath "experiments\templates\task-intake-template.csv"
$IncomingDocsDir = Resolve-ProjectPath $IncomingDocsDir (Join-Path "samples\owner-returned" $ImportId)

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

$SupportedDocExtensions = @(".pdf", ".docx", ".doc", ".html", ".htm")

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
    foreach ($char in [System.IO.Path]::GetInvalidFileNameChars()) {
        $source = $source.Replace([string]$char, "-")
    }

    $source = [regex]::Replace($source, "\s+", "-")
    $source = [regex]::Replace($source, "-+", "-").Trim(".-")
    if ([string]::IsNullOrWhiteSpace($source)) {
        return $Fallback
    }

    return $source
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

function Get-NextIdNumber {
    param(
        [object[]]$Rows,
        [string]$Column,
        [string]$Prefix
    )

    $maxNumber = 0
    foreach ($row in $Rows) {
        $value = [string]$row.$Column
        if ($value -match ("^{0}(\d+)$" -f [regex]::Escape($Prefix))) {
            $number = [int]$Matches[1]
            if ($number -gt $maxNumber) {
                $maxNumber = $number
            }
        }
    }

    return $maxNumber + 1
}

function Test-MeaningfulDocumentRow {
    param([object]$Row)

    foreach ($field in @("source_location", "document_title", "document_version", "owner", "candidate_reason")) {
        if (-not (Test-Placeholder $Row.$field)) {
            return $true
        }
    }

    return (Test-Affirmative $Row.allowed_for_experiment)
}

function Test-MeaningfulTaskRow {
    param([object]$Row)

    foreach ($field in @("real_source", "monthly_frequency", "task_description", "allowed_documents", "gold_answer_points", "required_constraints", "expected_evidence", "owner", "scorer")) {
        if (-not (Test-Placeholder $Row.$field)) {
            return $true
        }
    }

    return (Test-Affirmative $Row.selected)
}

function Resolve-PackageDocumentSource {
    param(
        [string]$Value,
        [string]$PackageRoot
    )

    if (Test-Placeholder $Value) {
        return $null
    }

    if (Test-ExternalSourceLocation $Value) {
        return $Value
    }

    $trimmed = $Value.Trim()
    if ([System.IO.Path]::IsPathRooted($trimmed)) {
        return $trimmed
    }

    $packageCandidate = Join-Path $PackageRoot $trimmed
    if (Test-Path -LiteralPath $packageCandidate -PathType Leaf) {
        return [System.IO.Path]::GetFullPath($packageCandidate)
    }

    return $trimmed
}

function Update-AllowedDocuments {
    param(
        [string]$Value,
        [hashtable]$IdMap
    )

    if (Test-Placeholder $Value) {
        return $Value
    }

    $parts = @($Value -split '[;,]' | ForEach-Object { $_.Trim() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $updated = @()
    foreach ($part in $parts) {
        if ($IdMap.ContainsKey($part)) {
            $updated += $IdMap[$part]
        }
        else {
            $updated += $part
        }
    }

    return ($updated -join ";")
}

if (-not (Test-Path -LiteralPath $PackagePath)) {
    Write-Error "Owner package path not found: $PackagePath"
}

if (-not (Test-Path -LiteralPath $DocumentIntakePath -PathType Leaf)) {
    Write-Error "Target document intake file not found: $DocumentIntakePath"
}
if (-not (Test-Path -LiteralPath $TaskIntakePath -PathType Leaf)) {
    Write-Error "Target task intake file not found: $TaskIntakePath"
}

$extractedRoot = $null
$packageRoot = $PackagePath
if ((Test-Path -LiteralPath $PackagePath -PathType Leaf) -and ([System.IO.Path]::GetExtension($PackagePath).ToLowerInvariant() -eq ".zip")) {
    if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
        New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
    }

    $extractedRoot = Join-Path $ArtifactRoot ("akh-owner-return-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
    New-Item -ItemType Directory -Path $extractedRoot -Force | Out-Null
    Expand-Archive -LiteralPath $PackagePath -DestinationPath $extractedRoot -Force
    $packageRoot = $extractedRoot
}

try {
    $packageDocumentPath = Join-Path $packageRoot "samples\document-intake-template.csv"
    $packageTaskPath = Join-Path $packageRoot "experiments\templates\task-intake-template.csv"

    if (-not (Test-Path -LiteralPath $packageDocumentPath -PathType Leaf)) {
        Write-Error "Returned package is missing samples\document-intake-template.csv"
    }
    if (-not (Test-Path -LiteralPath $packageTaskPath -PathType Leaf)) {
        Write-Error "Returned package is missing experiments\templates\task-intake-template.csv"
    }

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

    $requiredTaskColumns = @(
        "candidate_id",
        "task_type",
        "domain",
        "real_source",
        "monthly_frequency",
        "task_description",
        "allowed_documents",
        "gold_answer_points",
        "required_constraints",
        "expected_evidence",
        "owner",
        "scorer",
        "needs_evidence",
        "selected",
        "notes"
    )

    $returnedDocumentRows = @(Import-Csv -LiteralPath $packageDocumentPath -Encoding UTF8)
    $returnedTaskRows = @(Import-Csv -LiteralPath $packageTaskPath -Encoding UTF8)
    $targetDocumentRows = @(Import-Csv -LiteralPath $DocumentIntakePath -Encoding UTF8)
    $targetTaskRows = @(Import-Csv -LiteralPath $TaskIntakePath -Encoding UTF8)

    Assert-RequiredColumns $returnedDocumentRows $requiredDocumentColumns "Returned document intake"
    Assert-RequiredColumns $returnedTaskRows $requiredTaskColumns "Returned task intake"
    Assert-RequiredColumns $targetDocumentRows $requiredDocumentColumns "Target document intake"
    Assert-RequiredColumns $targetTaskRows $requiredTaskColumns "Target task intake"

    $meaningfulDocumentRows = @($returnedDocumentRows | Where-Object { Test-MeaningfulDocumentRow $_ })
    $meaningfulTaskRows = @($returnedTaskRows | Where-Object { Test-MeaningfulTaskRow $_ })

    $nextDocumentId = Get-NextIdNumber $targetDocumentRows "candidate_id" "doc-candidate-"
    $nextTaskId = Get-NextIdNumber $targetTaskRows "candidate_id" "task-candidate-"
    $documentIdMap = @{}
    $importedDocumentRows = @()
    $documentCopyPlans = @()

    foreach ($row in $meaningfulDocumentRows) {
        $oldId = if (Test-Placeholder $row.candidate_id) { "returned-doc-$nextDocumentId" } else { $row.candidate_id.Trim() }
        $newId = "doc-candidate-{0:000}" -f $nextDocumentId
        $nextDocumentId++
        $documentIdMap[$oldId] = $newId

        if (-not [string]::IsNullOrWhiteSpace($Owner) -and (Test-Placeholder $row.owner)) {
            $row.owner = $Owner
        }

        $sourceLocation = Resolve-PackageDocumentSource $row.source_location $packageRoot
        if ($null -ne $sourceLocation -and -not (Test-ExternalSourceLocation $sourceLocation) -and [System.IO.Path]::IsPathRooted($sourceLocation) -and (Test-Path -LiteralPath $sourceLocation -PathType Leaf)) {
            $extension = [System.IO.Path]::GetExtension($sourceLocation).ToLowerInvariant()
            if ($SupportedDocExtensions -contains $extension) {
                $safeStem = ConvertTo-SafeFileStem $newId $newId
                $destinationPath = Join-Path $IncomingDocsDir ($safeStem + $extension)
                $documentCopyPlans += [pscustomobject]@{
                    SourcePath = [System.IO.Path]::GetFullPath($sourceLocation)
                    DestinationPath = [System.IO.Path]::GetFullPath($destinationPath)
                }
                $sourceLocation = Get-RelativeProjectPath $destinationPath
            }
        }

        $notes = "imported from owner package $ImportId"
        if (-not (Test-Placeholder $row.notes)) {
            $notes = "$notes; $($row.notes)"
        }

        $importedDocumentRows += [pscustomobject]@{
            candidate_id = $newId
            slot_type = $row.slot_type
            source_location = $sourceLocation
            document_title = $row.document_title
            document_version = $row.document_version
            owner = $row.owner
            is_scanned = $row.is_scanned
            has_tables = $row.has_tables
            has_multicolumn = $row.has_multicolumn
            confidentiality = $row.confidentiality
            allowed_for_experiment = $row.allowed_for_experiment
            candidate_reason = $row.candidate_reason
            notes = $notes
        }
    }

    $importedTaskRows = @()
    foreach ($row in $meaningfulTaskRows) {
        $newId = "task-candidate-{0:000}" -f $nextTaskId
        $nextTaskId++

        if (-not [string]::IsNullOrWhiteSpace($Owner) -and (Test-Placeholder $row.owner)) {
            $row.owner = $Owner
        }

        $notes = "imported from owner package $ImportId"
        if (-not (Test-Placeholder $row.notes)) {
            $notes = "$notes; $($row.notes)"
        }

        $importedTaskRows += [pscustomobject]@{
            candidate_id = $newId
            task_type = $row.task_type
            domain = $row.domain
            real_source = $row.real_source
            monthly_frequency = $row.monthly_frequency
            task_description = $row.task_description
            allowed_documents = (Update-AllowedDocuments $row.allowed_documents $documentIdMap)
            gold_answer_points = $row.gold_answer_points
            required_constraints = $row.required_constraints
            expected_evidence = $row.expected_evidence
            owner = $row.owner
            scorer = $row.scorer
            needs_evidence = $row.needs_evidence
            selected = $row.selected
            notes = $notes
        }
    }

    Write-Host "Agent Knowledge Hub owner package import"
    Write-Host "Project root: $ProjectRoot"
    Write-Host "Package path: $PackagePath"
    Write-Host "Package root: $packageRoot"
    Write-Host "Target document intake: $DocumentIntakePath"
    Write-Host "Target task intake: $TaskIntakePath"
    Write-Host "Incoming docs dir: $IncomingDocsDir"
    Write-Host "Mode: $(if ($Apply) { 'apply' } else { 'dry run' })"
    Write-Host ""
    Write-Host "Meaningful returned documents: $($meaningfulDocumentRows.Count)"
    Write-Host "Meaningful returned tasks: $($meaningfulTaskRows.Count)"
    Write-Host "Document rows to import: $($importedDocumentRows.Count)"
    Write-Host "Task rows to import: $($importedTaskRows.Count)"
    Write-Host "Document files to copy: $($documentCopyPlans.Count)"

    if ($importedDocumentRows.Count -eq 0 -and $importedTaskRows.Count -eq 0) {
        Write-Error "No meaningful owner input rows found in returned package."
    }

    if ($documentCopyPlans.Count -gt 0) {
        Write-Host ""
        Write-Host "Planned returned document copies:"
        foreach ($plan in $documentCopyPlans) {
            Write-Host ("- {0} -> {1}" -f $plan.SourcePath, $plan.DestinationPath)
        }
    }

    if (-not $Apply) {
        Write-Host ""
        Write-Host "Dry run only. Use -Apply to append imported rows and copy returned document files."
        Write-Host "OWNER_PACKAGE_IMPORT_DRY_RUN=PASS"
        exit 0
    }

    foreach ($plan in $documentCopyPlans) {
        if ((Test-Path -LiteralPath $plan.DestinationPath) -and -not $Force) {
            Write-Error "Refusing to overwrite returned document without -Force: $($plan.DestinationPath)"
        }
    }

    if (-not (Test-Path -LiteralPath $IncomingDocsDir)) {
        New-Item -ItemType Directory -Path $IncomingDocsDir -Force | Out-Null
    }

    foreach ($plan in $documentCopyPlans) {
        Copy-Item -LiteralPath $plan.SourcePath -Destination $plan.DestinationPath -Force:$Force
    }

    $documentBackupPath = Join-Path (Split-Path -Parent $DocumentIntakePath) ("document-intake-template.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".csv")
    $taskBackupPath = Join-Path (Split-Path -Parent $TaskIntakePath) ("task-intake-template.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".csv")
    Copy-Item -LiteralPath $DocumentIntakePath -Destination $documentBackupPath
    Copy-Item -LiteralPath $TaskIntakePath -Destination $taskBackupPath

    @($targetDocumentRows + $importedDocumentRows) |
        Select-Object $requiredDocumentColumns |
        Export-Csv -LiteralPath $DocumentIntakePath -NoTypeInformation -Encoding UTF8

    @($targetTaskRows + $importedTaskRows) |
        Select-Object $requiredTaskColumns |
        Export-Csv -LiteralPath $TaskIntakePath -NoTypeInformation -Encoding UTF8

    Write-Host ""
    Write-Host "Document intake backup: $documentBackupPath"
    Write-Host "Task intake backup: $taskBackupPath"
    Write-Host "OWNER_PACKAGE_IMPORT_APPLY=PASS"
}
finally {
    if ($null -ne $extractedRoot -and -not $KeepExtracted -and (Test-Path -LiteralPath $extractedRoot)) {
        Remove-Item -LiteralPath $extractedRoot -Recurse -Force
        Write-Host "EXTRACTED_PACKAGE_CLEANED=$extractedRoot"
    }
    elseif ($null -ne $extractedRoot -and $KeepExtracted) {
        Write-Host "EXTRACTED_PACKAGE_KEPT=$extractedRoot"
    }
}

exit 0
