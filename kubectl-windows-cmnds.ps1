$nodeName = Read-Host "Enter the node name to filter pods"
$podCount = (kubectl get pods -o wide | Where-Object { $_ -match $nodeName }).Count
Write-Output "Number of pods on node '$nodeName': $podCount"