param(
    [string]$OutputDir,
    [switch]$Force,
    [switch]$CreateZip,
    [string]$ZipPath,
    [string]$Owner,
    [string]$Module,
    [string]$DueDate,
    [string]$RequestedDocuments = "2-3",
    [string]$RequestedTasks = "1-2",
    [switch]$UpdateTracker,
    [string]$TrackerPath
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

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

if ([string]::IsNullOrWhiteSpace($Module)) {
    $Module = "mixed engineering documents"
}

if ([string]::IsNullOrWhiteSpace($DueDate)) {
    $DueDate = (Get-Date).AddDays(5).ToString("yyyy-MM-dd")
}

if ($UpdateTracker -and [string]::IsNullOrWhiteSpace($Owner)) {
    Write-Error "Owner is required when -UpdateTracker is used."
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $artifactRoot = (Join-Path ([System.IO.Path]::GetTempPath()) "ai-knowledge-foundation-artifacts")
    $OutputDir = Join-Path $artifactRoot ("akh-owner-package-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}
elseif (-not [System.IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir = Join-Path $ProjectRoot $OutputDir
}

$TrackerPath = Resolve-ProjectPath $TrackerPath "samples\owner-response-tracker.csv"

if ($CreateZip -and [string]::IsNullOrWhiteSpace($ZipPath)) {
    $ZipPath = "$OutputDir.zip"
}
elseif (-not [string]::IsNullOrWhiteSpace($ZipPath) -and -not [System.IO.Path]::IsPathRooted($ZipPath)) {
    $ZipPath = Join-Path $ProjectRoot $ZipPath
}

function Copy-RequiredFile {
    param(
        [string]$SourceRelativePath,
        [string]$DestinationRelativePath
    )

    $sourcePath = Join-Path $ProjectRoot $SourceRelativePath
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        Write-Error "Missing required file: $sourcePath"
    }

    $destinationPath = Join-Path $OutputDir $DestinationRelativePath
    $destinationParent = Split-Path -Parent $destinationPath
    if (-not (Test-Path -LiteralPath $destinationParent)) {
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    }

    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
    return [pscustomobject]@{
        source = $SourceRelativePath
        package_path = $DestinationRelativePath
    }
}

function Copy-RequiredPattern {
    param(
        [string]$SourcePattern,
        [string]$DestinationDir
    )

    $sourceGlob = Join-Path $ProjectRoot $SourcePattern
    $matches = @(Get-ChildItem -Path $sourceGlob -File -ErrorAction SilentlyContinue)
    if ($matches.Count -eq 0) {
        Write-Error "Missing required pattern: $SourcePattern"
    }

    $copied = @()
    foreach ($match in $matches) {
        $relativeDestination = Join-Path $DestinationDir $match.Name
        $destinationPath = Join-Path $OutputDir $relativeDestination
        $destinationParent = Split-Path -Parent $destinationPath
        if (-not (Test-Path -LiteralPath $destinationParent)) {
            New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        }

        Copy-Item -LiteralPath $match.FullName -Destination $destinationPath -Force
        $copied += [pscustomobject]@{
            source = $SourcePattern
            package_path = $relativeDestination
        }
    }

    return $copied
}

if (Test-Path -LiteralPath $OutputDir) {
    if (-not $Force) {
        Write-Error "Output directory already exists. Use -Force to overwrite package files: $OutputDir"
    }
}
else {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$copiedFiles = @()

$copiedFiles += Copy-RequiredFile "docs\overview.md" "docs\overview.md"
$copiedFiles += Copy-RequiredFile "docs\evaluation.md" "docs\evaluation.md"
$copiedFiles += Copy-RequiredFile "docs\operations.md" "docs\operations.md"
$copiedFiles += Copy-RequiredFile "docs\archive\06-operations\owner-collection-package.md" "docs\owner-collection-package.md"
$copiedFiles += Copy-RequiredFile "docs\archive\06-operations\owner-response-tracking.md" "docs\owner-response-tracking.md"

$copiedFiles += Copy-RequiredFile "samples\document-intake-template.csv" "samples\document-intake-template.csv"
$copiedFiles += Copy-RequiredFile "samples\document-intake-example.csv" "samples\document-intake-example.csv"
$copiedFiles += Copy-RequiredFile "samples\owner-response-tracker.csv" "samples\owner-response-tracker.csv"
$copiedFiles += Copy-RequiredFile "experiments\templates\task-intake-template.csv" "experiments\templates\task-intake-template.csv"
$copiedFiles += Copy-RequiredFile "experiments\templates\task-intake-example.csv" "experiments\templates\task-intake-example.csv"

$readmeLines = @(
    "# Agent Knowledge Hub Owner Intake Package",
    "",
    "Purpose:",
    "",
    "Collect the minimum real inputs needed to run the Phase 1 experiment.",
    "",
    "Phase 1 validates whether structured document retrieval plus Context Pack is better than giving raw files directly to an Agent.",
    "",
    "Owner should fill:",
    "",
    "- samples/document-intake-template.csv",
    "- experiments/templates/task-intake-template.csv",
    "",
    "Reference examples:",
    "",
    "- samples/document-intake-example.csv",
    "- experiments/templates/task-intake-example.csv",
    "",
    "Before returning the package, check:",
    "",
    "- OWNER_CHECKLIST.md",
    "",
    "Detailed Chinese instructions are included under docs/.",
    "",
    "Required minimum across all owners:",
    "",
    "- 10 real engineering documents",
    "- 3 real Agent tasks",
    "- 3 task types",
    "- at least 1 table-heavy document",
    "- at least 1 multicolumn document",
    "- at least 1 scanned or OCR-risk document",
    "",
    "Do not ask owners to design graphs, review consoles, version invalidation, IDE plugins, MCP, or API implementation in this phase.",
    "",
    "After intake is returned, copy the filled CSV files back to the project and run:",
    "",
    '```powershell',
    ('powershell -ExecutionPolicy Bypass -File "{0}" -Strict' -f (Join-Path $ProjectRoot "scripts\check-intake-readiness.ps1")),
    '```',
    "",
    "Use the project-local path when running the command."
)

$ownerReadmePath = Join-Path $OutputDir "OWNER_README.md"
Set-Content -LiteralPath $ownerReadmePath -Value $readmeLines -Encoding UTF8
$copiedFiles += [pscustomobject]@{
    source = "<generated>"
    package_path = "OWNER_README.md"
}

$messageLines = @(
    "Subject: Agent Knowledge Hub engineering document intake request",
    "",
    "We are preparing the Phase 1 Agent Knowledge Hub experiment.",
    "",
    "This phase only validates whether structured document retrieval plus Context Pack is better than giving raw files directly to an Agent.",
    "",
    "Please provide:",
    "",
    "1. Documents",
    "   - $RequestedDocuments real engineering documents that Agents often need.",
    "   - Prefer documents with versions, tables, interface limits, platform constraints, startup / IPC / service mechanism notes.",
    "   - Confirm whether each document is allowed for this experiment.",
    "",
    "2. Real Agent tasks",
    "   - $RequestedTasks real tasks from recent work, such as constraint lookup, interface/mechanism lookup, or test focus generation.",
    "   - Each task needs gold answer points.",
    "   - Each task needs expected evidence location: document, section/page, or original text span if known.",
    "",
    "Please fill these files in the package:",
    "",
    "- samples/document-intake-template.csv",
    "- experiments/templates/task-intake-template.csv",
    "",
    "Please review OWNER_CHECKLIST.md before returning the package.",
    "",
    "Reference examples and detailed Chinese instructions are included in the package.",
    "",
    "Do not design graph schema, review workflow, version invalidation, MCP, API, or IDE plugin for this phase.",
    "",
    "Due date: $DueDate"
)

$ownerMessagePath = Join-Path $OutputDir "OWNER_MESSAGE.txt"
Set-Content -LiteralPath $ownerMessagePath -Value $messageLines -Encoding UTF8
$copiedFiles += [pscustomobject]@{
    source = "<generated>"
    package_path = "OWNER_MESSAGE.txt"
}

$ownerChecklistPath = Join-Path $OutputDir "OWNER_CHECKLIST.md"
$ownerChecklistLines = @(
    "# Owner Return Checklist",
    "",
    "Before returning the owner package, confirm these items.",
    "",
    "## Document Intake",
    "",
    "- Fill `samples/document-intake-template.csv`.",
    "- Provide 2-3 real engineering documents when possible.",
    "- `source_location` must be reachable or clearly describe the handoff path.",
    "- `document_title`, `document_version`, `owner`, and `allowed_for_experiment` must be filled.",
    "- Mark whether each document is scanned, table-heavy, or multicolumn.",
    "",
    "## Task Intake",
    "",
    "- Fill `experiments/templates/task-intake-template.csv`.",
    "- Provide 1-2 real Agent tasks from recent work when possible.",
    "- `task_description` must be executable by an Agent.",
    "- `gold_answer_points`, `required_constraints`, and `expected_evidence` are required for selected tasks.",
    "- `scorer`, `needs_evidence`, and `selected` must be filled for selected tasks.",
    "",
    "## Project-Side Check",
    "",
    "After the package is returned, the project side runs:",
    "",
    '```powershell',
    'powershell -ExecutionPolicy Bypass -File ".\scripts\check-intake-readiness.ps1" -Strict',
    '```',
    "",
    "The package is ready only when the recommendation is:",
    "",
    '```text',
    "Recommendation: READY_TO_CREATE_EXPERIMENT_RUN",
    '```'
)
Set-Content -LiteralPath $ownerChecklistPath -Value $ownerChecklistLines -Encoding UTF8
$copiedFiles += [pscustomobject]@{
    source = "<generated>"
    package_path = "OWNER_CHECKLIST.md"
}

$manifestPath = Join-Path $OutputDir "owner-package-manifest.csv"
$copiedFiles |
    Sort-Object package_path |
    Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding UTF8

if ($CreateZip) {
    $zipParent = Split-Path -Parent $ZipPath
    if (-not [string]::IsNullOrWhiteSpace($zipParent) -and -not (Test-Path -LiteralPath $zipParent)) {
        New-Item -ItemType Directory -Path $zipParent -Force | Out-Null
    }

    if (Test-Path -LiteralPath $ZipPath) {
        if (-not $Force) {
            Write-Error "Zip file already exists. Use -Force to overwrite: $ZipPath"
        }
        Remove-Item -LiteralPath $ZipPath -Force
    }

    Compress-Archive -Path (Join-Path $OutputDir "*") -DestinationPath $ZipPath -Force
}

$readinessScript = Join-Path $PSScriptRoot "check-owner-package-readiness.ps1"
if (-not (Test-Path -LiteralPath $readinessScript -PathType Leaf)) {
    Write-Error "Missing owner package readiness script: $readinessScript"
}

$packageToValidate = if ($CreateZip) { $ZipPath } else { $OutputDir }
& powershell -ExecutionPolicy Bypass -File $readinessScript -PackagePath $packageToValidate -Strict
$readinessExitCode = $LASTEXITCODE
if ($readinessExitCode -ne 0) {
    Write-Error "Owner package readiness check failed. Tracker was not updated."
}

if ($UpdateTracker) {
    if (-not (Test-Path -LiteralPath $TrackerPath -PathType Leaf)) {
        Write-Error "Missing owner tracker: $TrackerPath"
    }

    $trackerRows = @(Import-Csv -LiteralPath $TrackerPath -Encoding UTF8)
    $trackerColumns = @(
        "owner",
        "module",
        "request_sent_date",
        "due_date",
        "requested_documents",
        "provided_documents",
        "requested_tasks",
        "provided_tasks",
        "document_intake_updated",
        "task_intake_updated",
        "current_status",
        "blocker",
        "next_follow_up",
        "notes"
    )

    $today = Get-Date -Format "yyyy-MM-dd"
    $nextFollowUp = (Get-Date).AddDays(2).ToString("yyyy-MM-dd")
    $packageNote = "owner package exported: $OutputDir"
    if ($CreateZip) {
        $packageNote = "$packageNote; zip: $ZipPath"
    }

    $newRow = [pscustomobject]@{
        owner = $Owner
        module = $Module
        request_sent_date = $today
        due_date = $DueDate
        requested_documents = $RequestedDocuments
        provided_documents = "0"
        requested_tasks = $RequestedTasks
        provided_tasks = "0"
        document_intake_updated = "no"
        task_intake_updated = "no"
        current_status = "sent"
        blocker = ""
        next_follow_up = $nextFollowUp
        notes = $packageNote
    }

    $trackerRows = @($trackerRows) + $newRow
    $trackerRows |
        Select-Object $trackerColumns |
        Export-Csv -LiteralPath $TrackerPath -NoTypeInformation -Encoding UTF8
}

Write-Host "Agent Knowledge Hub owner package"
Write-Host "Project root: $ProjectRoot"
Write-Host "Output dir: $OutputDir"
if ($CreateZip) {
    Write-Host "Zip path: $ZipPath"
}
if ($UpdateTracker) {
    Write-Host "Tracker updated: $TrackerPath"
}
Write-Host "Files: $($copiedFiles.Count)"
Write-Host "Manifest: $manifestPath"
Write-Host "OWNER_PACKAGE_READY"

exit 0
