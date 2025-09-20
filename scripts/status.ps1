# This script has been moved to the root directory
# Please use ..\manage.ps1 -Action status instead

Write-Host "This script has been consolidated and moved to the root directory."
Write-Host "Please use: ..\manage.ps1 -Action status"
Write-Host ""
Write-Host "Available management commands:"
Write-Host "  ..\manage.ps1 -Action status     # Show cluster status"
Write-Host "  ..\manage.ps1 -Action pause      # Pause cluster to save costs"
Write-Host "  ..\manage.ps1 -Action resume     # Resume paused cluster"
Write-Host "  ..\manage.ps1 -Action debug      # Debug cluster issues"
Write-Host "  ..\manage.ps1 -Action logs -AppName <app>  # View application logs"