param(
  [Parameter(Mandatory=$false)][string]$Repo = $env:PII_REPO_URL,
  [Parameter(Mandatory=$false)][string]$Ref = $env:PII_REPO_REF,
  [Parameter(Mandatory=$false)][string]$OpenApiPath = $env:PII_OPENAPI_PATH
)

if (-not $Repo) {
  Write-Error "PII_REPO_URL is required (or pass -Repo)."
  exit 2
}

if (-not $Ref) { $Ref = "main" }
if (-not $OpenApiPath) { $OpenApiPath = "openapi.yaml" }

python ".\scripts\sync_pii_openapi.py" --repo "$Repo" --ref "$Ref" --openapi-path "$OpenApiPath"

