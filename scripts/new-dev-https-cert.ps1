param(
  [string]$OutDir = "certs",
  [string[]]$DnsName = @("localhost"),
  [string[]]$IpAddress = @("127.0.0.1", "::1"),
  [switch]$TrustRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function ConvertTo-Pem {
  param(
    [Parameter(Mandatory = $true)][string]$Label,
    [Parameter(Mandatory = $true)][byte[]]$Data
  )
  $base64 = [Convert]::ToBase64String($Data)
  $lines = for ($index = 0; $index -lt $base64.Length; $index += 64) {
    $base64.Substring($index, [Math]::Min(64, $base64.Length - $index))
  }
  "-----BEGIN $Label-----`n$($lines -join "`n")`n-----END $Label-----`n"
}

$resolvedOutDir = Join-Path (Resolve-Path -LiteralPath ".").Path $OutDir
New-Item -ItemType Directory -Path $resolvedOutDir -Force | Out-Null

$sanBuilder = [System.Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
$uniqueDnsNames = New-Object System.Collections.Generic.HashSet[string]
foreach ($name in $DnsName) {
  $trimmed = $name.Trim()
  if ($trimmed -ne "" -and $uniqueDnsNames.Add($trimmed)) {
    $sanBuilder.AddDnsName($trimmed)
  }
}

$uniqueIpAddresses = New-Object System.Collections.Generic.HashSet[string]
foreach ($address in $IpAddress) {
  $trimmed = $address.Trim()
  if ($trimmed -eq "" -or -not $uniqueIpAddresses.Add($trimmed)) {
    continue
  }
  $parsed = [System.Net.IPAddress]::Parse($trimmed)
  $sanBuilder.AddIpAddress($parsed)
}

Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Where-Object { $_.IPAddress -notlike "169.254.*" } |
  ForEach-Object {
    if ($uniqueIpAddresses.Add($_.IPAddress)) {
      $sanBuilder.AddIpAddress([System.Net.IPAddress]::Parse($_.IPAddress))
    }
  }

$rootKey = [System.Security.Cryptography.RSA]::Create(2048)
$rootRequest = [System.Security.Cryptography.X509Certificates.CertificateRequest]::new(
  "CN=CaseClosed Local Development Root CA",
  $rootKey,
  [System.Security.Cryptography.HashAlgorithmName]::SHA256,
  [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
)
$rootRequest.CertificateExtensions.Add(
  [System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($true, $false, 0, $true)
)
$rootRequest.CertificateExtensions.Add(
  [System.Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new(
    [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyCertSign -bor
      [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::CrlSign,
    $true
  )
)
$rootRequest.CertificateExtensions.Add(
  [System.Security.Cryptography.X509Certificates.X509SubjectKeyIdentifierExtension]::new($rootRequest.PublicKey, $false)
)
$rootNotBefore = [DateTimeOffset]::Now.AddDays(-1)
$rootNotAfter = $rootNotBefore.AddYears(5)
$rootCertificate = $rootRequest.CreateSelfSigned($rootNotBefore, $rootNotAfter)

$serverKey = [System.Security.Cryptography.RSA]::Create(2048)
$request = [System.Security.Cryptography.X509Certificates.CertificateRequest]::new(
  "CN=CaseClosed Dev HTTPS",
  $serverKey,
  [System.Security.Cryptography.HashAlgorithmName]::SHA256,
  [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
)
$request.CertificateExtensions.Add(
  [System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]::new($false, $false, 0, $true)
)
$request.CertificateExtensions.Add(
  [System.Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new(
    [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature -bor
      [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyEncipherment,
    $true
  )
)
$serverAuthOid = [System.Security.Cryptography.Oid]::new("1.3.6.1.5.5.7.3.1")
$enhancedUsages = [System.Security.Cryptography.OidCollection]::new()
$null = $enhancedUsages.Add($serverAuthOid)
$request.CertificateExtensions.Add(
  [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]::new($enhancedUsages, $true)
)
$request.CertificateExtensions.Add($sanBuilder.Build())

$notBefore = [DateTimeOffset]::Now.AddDays(-1)
$notAfter = $notBefore.AddYears(2)
$serialNumber = New-Object byte[] 16
$random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
  $random.GetBytes($serialNumber)
}
finally {
  $random.Dispose()
}
$certificate = $request.Create($rootCertificate, $notBefore, $notAfter, $serialNumber)

$certWithKey = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::CopyWithPrivateKey(
  $certificate,
  $serverKey
)
$certPem = ConvertTo-Pem -Label "CERTIFICATE" -Data $certWithKey.GetRawCertData()
$pfxBytes = $certWithKey.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Pfx, "")
$rootPem = ConvertTo-Pem -Label "CERTIFICATE" -Data $rootCertificate.GetRawCertData()

$certPath = Join-Path $resolvedOutDir "caseclosed-dev-cert.pem"
$pfxPath = Join-Path $resolvedOutDir "caseclosed-dev.pfx"
$rootCertPath = Join-Path $resolvedOutDir "caseclosed-local-root-ca.pem"
$rootCerPath = Join-Path $resolvedOutDir "caseclosed-local-root-ca.cer"
[System.IO.File]::WriteAllText($certPath, $certPem, [System.Text.Encoding]::ASCII)
[System.IO.File]::WriteAllBytes($pfxPath, $pfxBytes)
[System.IO.File]::WriteAllText($rootCertPath, $rootPem, [System.Text.Encoding]::ASCII)
[System.IO.File]::WriteAllBytes($rootCerPath, $rootCertificate.GetRawCertData())

if ($TrustRoot) {
  $store = [System.Security.Cryptography.X509Certificates.X509Store]::new(
    [System.Security.Cryptography.X509Certificates.StoreName]::Root,
    [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser
  )
  $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
  try {
    $store.Add($rootCertificate)
  }
  finally {
    $store.Close()
  }
}

Write-Output "Wrote certificate: $certPath"
Write-Output "Wrote HTTPS certificate bundle: $pfxPath"
Write-Output "Wrote root CA certificate: $rootCertPath"
Write-Output "Wrote Windows root CA certificate: $rootCerPath"
if ($TrustRoot) {
  Write-Output "Trusted root CA in CurrentUser Root store."
}
