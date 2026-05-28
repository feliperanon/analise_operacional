# Deploy no Cloud Run + Cloud SQL (projeto estoquesouzapinto).
# Uso: .\scripts\gcp_cloud_run_deploy.ps1
# Antes: gcloud auth login && gcloud config set project estoquesouzapinto

$ErrorActionPreference = "Stop"
$Project = "estoquesouzapinto"
$Region = "us-central1"
$Service = "analise-operacional"
$SqlInstance = "estoquesouzapinto:us-central1:estoquesouzapinto"
$SecretName = "cloud-sql-password"

Write-Host "Projeto: $Project | Regiao: $Region | Servico: $Service"

gcloud config set project $Project | Out-Null

# Secret da senha do Postgres (cria se nao existir)
$secretExists = gcloud secrets describe $SecretName 2>$null
if (-not $secretExists) {
    if (-not $env:CLOUD_SQL_PASSWORD) {
        $secure = Read-Host "Senha do usuario postgres no Cloud SQL" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        $env:CLOUD_SQL_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    }
    $env:CLOUD_SQL_PASSWORD | gcloud secrets create $SecretName --data-file=-
    Write-Host "Secret $SecretName criado."
} else {
    Write-Host "Secret $SecretName ja existe."
}

# Conta de servico padrao do Cloud Run precisa ler o secret e o Cloud SQL
$projectNumber = (gcloud projects describe $Project --format="value(projectNumber)")
$runSa = "$projectNumber-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding $SecretName `
    --member="serviceAccount:$runSa" `
    --role="roles/secretmanager.secretAccessor" | Out-Null
gcloud projects add-iam-policy-binding $Project `
    --member="serviceAccount:$runSa" `
    --role="roles/cloudsql.client" | Out-Null

# APP_BASE_URL: atualize depois do primeiro deploy com a URL real do servico
$appBase = $env:APP_BASE_URL
if (-not $appBase) { $appBase = "https://PLACEHOLDER.run.app" }

gcloud run deploy $Service `
    --source . `
    --region $Region `
    --allow-unauthenticated `
    --add-cloudsql-instances $SqlInstance `
    --set-env-vars "USE_CLOUD_SQL_CONNECTOR=true,CLOUD_SQL_CONNECTION_NAME=$SqlInstance,CLOUD_SQL_USER=postgres,CLOUD_SQL_DB=analise,REQUIRE_GCP_DB=true,GCP=true,ENV=production,ENVIRONMENT=production,TRUST_PROXY_HEADERS=true,APP_BASE_URL=$appBase" `
    --set-secrets "CLOUD_SQL_PASSWORD=${SecretName}:latest"

Write-Host ""
Write-Host "Deploy enviado. URL:"
gcloud run services describe $Service --region $Region --format="value(status.url)"
