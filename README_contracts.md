## Contracts (OpenAPI mirrors)

Зеркало OpenAPI контракта PII сервиса:
- `contracts/pii/openapi.yaml`
- `contracts/pii/SYNCED_FROM.txt` (repo/ref/path/time)

Ожидаемая совместимость: `api_version=1` (см. `/health` в OpenAPI).

## Sync PII contract

### PowerShell
```powershell
$env:PII_REPO_URL="https://github.com/<org>/<pii-masking-service>.git"
$env:PII_REPO_REF="v0.1.0"
$env:PII_OPENAPI_PATH="openapi.yaml"
.\scripts\sync_pii_openapi.ps1
```

### Python
```powershell
python .\scripts\sync_pii_openapi.py --repo "..." --ref "v0.1.0" --openapi-path "openapi.yaml"
```

После sync закоммитьте изменения в:
- `contracts/pii/openapi.yaml`
- `contracts/pii/SYNCED_FROM.txt`

