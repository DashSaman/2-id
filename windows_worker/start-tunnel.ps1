param(
    [Parameter(Mandatory=$true)][string]$Server,
    [string]$User = "root"
)

Write-Host "Opening an SSH tunnel from local 127.0.0.1:18220 to the private 2-id API."
Write-Host "Keep this window open while the Windows worker is running."
ssh -N -L 18220:127.0.0.1:18220 "$User@$Server"
