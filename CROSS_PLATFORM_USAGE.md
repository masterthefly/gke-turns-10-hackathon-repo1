# Cross-Platform Usage Guide

This project now includes both PowerShell (.ps1) and Shell (.sh) scripts for cross-platform compatibility.

## Script Equivalents

| PowerShell Script | Shell Script | Description |
|-------------------|--------------|-------------|
| `setup.ps1` | `setup.sh` | Initial project and GKE setup |
| `deploy.ps1` | `deploy.sh` | Deploy infrastructure and applications |
| `manage.ps1` | `manage.sh` | Cluster management (status, pause, resume, debug) |
| `teardown.ps1` | `teardown.sh` | Clean up and destroy resources |

## Platform-Specific Usage

### Windows (PowerShell)
```powershell
# Setup
.\setup.ps1 -ProjectId "my-project" -BillingAccountId "123456" -GeminiApiKey "your-key"

# Deploy
.\deploy.ps1 -ProjectId "my-project" -GeminiApiKey "your-key"

# Manage
.\manage.ps1 -Action status
.\manage.ps1 -Action pause
.\manage.ps1 -Action resume

# Teardown
.\teardown.ps1 -ProjectId "my-project"
.\teardown.ps1 -ProjectId "my-project" -DeleteProject  # Complete deletion
```

### Linux/Mac (Bash)
```bash
# Setup
./setup.sh -p "my-project" -b "123456" -g "your-key"

# Deploy  
./deploy.sh -p "my-project" -g "your-key"

# Manage
./manage.sh status
./manage.sh pause
./manage.sh resume

# Teardown
./teardown.sh -p "my-project"
./teardown.sh -p "my-project" -d  # Complete deletion
```

## Command Line Arguments

### Setup Script
| PowerShell | Shell | Description |
|------------|-------|-------------|
| `-ProjectId` | `-p, --project-id` | GCP Project ID |
| `-BillingAccountId` | `-b, --billing-account-id` | GCP Billing Account ID |
| `-GeminiApiKey` | `-g, --gemini-api-key` | Gemini API Key |
| `-Region` | `-r, --region` | GCP Region (default: us-central1) |
| `-Zone` | `-z, --zone` | GCP Zone (default: us-central1-a) |

### Deploy Script
| PowerShell | Shell | Description |
|------------|-------|-------------|
| `-ProjectId` | `-p, --project-id` | GCP Project ID |
| `-GeminiApiKey` | `-g, --gemini-api-key` | Gemini API Key |
| `-SkipInfrastructure` | `-s, --skip-infrastructure` | Skip Terraform deployment |
| `-ForceRedeploy` | `-f, --force-redeploy` | Force redeploy existing services |

### Manage Script
| PowerShell | Shell | Description |
|------------|-------|-------------|
| `-Action` | First argument | Action: status, pause, resume, debug, logs |
| `-ProjectId` | `-p, --project-id` | GCP Project ID |
| `-AppName` | `-n, --app-name` | Application name for logs |

### Teardown Script
| PowerShell | Shell | Description |
|------------|-------|-------------|
| `-ProjectId` | `-p, --project-id` | GCP Project ID |
| `-DeleteProject` | `-d, --delete-project` | Delete entire project |
| `-Force` | `-f, --force` | Skip confirmation prompts |

## Prerequisites

### All Platforms
- Google Cloud SDK (gcloud)
- kubectl
- Docker
- Terraform (optional)

### Installation Links
- **Google Cloud SDK**: https://cloud.google.com/sdk/docs/install
- **kubectl**: https://kubernetes.io/docs/tasks/tools/
- **Docker**: 
  - Windows: Docker Desktop
  - Linux: https://docs.docker.com/engine/install/
  - Mac: Docker Desktop
- **Terraform**: https://www.terraform.io/downloads

## Configuration Files

Both script types can use configuration files to store common settings:

### PowerShell: `.setup-config.ps1`
```powershell
$env:PROJECT_ID = "my-project"
$env:REGION = "us-central1"
$env:ZONE = "us-central1-a"
$env:GEMINI_API_KEY = "your-key"
```

### Shell: `.setup-config.sh`
```bash
export PROJECT_ID="my-project"
export REGION="us-central1"  
export ZONE="us-central1-a"
export GEMINI_API_KEY="your-key"
```

Load configuration:
```powershell
# PowerShell
. ./.setup-config.ps1
```
```bash
# Bash
source .setup-config.sh
```

## Help and Usage

All scripts support help flags:

```bash
# PowerShell
Get-Help .\setup.ps1
.\setup.ps1 -?

# Shell  
./setup.sh -h
./setup.sh --help
```

## Cost Management

Both script types support the same cost-saving features:

1. **Pause Cluster**: Scale down to minimize costs while preserving state
   ```bash
   ./manage.sh pause    # Shell
   .\manage.ps1 -Action pause    # PowerShell
   ```

2. **Resume Cluster**: Restore full functionality
   ```bash
   ./manage.sh resume   # Shell
   .\manage.ps1 -Action resume   # PowerShell
   ```

3. **Status Check**: Monitor costs and resource usage
   ```bash
   ./manage.sh status   # Shell
   .\manage.ps1 -Action status   # PowerShell
   ```

## Differences Between Platforms

### Functional Differences
- **None**: Both script types provide identical functionality
- All features work the same way across platforms
- Cost calculations and estimates are identical

### Syntax Differences
- **PowerShell**: Uses named parameters (`-Action status`)
- **Shell**: Uses positional arguments and flags (`status` or `--action status`)
- **Confirmation prompts**: Slightly different formatting but same behavior
- **Error handling**: Both provide user-friendly error messages

### File Paths
- **PowerShell**: Uses Windows-style paths with backslashes
- **Shell**: Uses Unix-style paths with forward slashes
- **Both**: Handle relative and absolute paths appropriately

## Troubleshooting

### Common Issues

1. **Permission Denied (Linux/Mac)**
   ```bash
   chmod +x *.sh
   ```

2. **Script Not Found**
   ```bash
   # Ensure you're in the correct directory
   cd /path/to/gke-turns-10-hackathon
   ```

3. **gcloud Not Found**
   ```bash
   # Install Google Cloud SDK and restart terminal
   gcloud auth login
   ```

4. **Docker Not Running**
   ```bash
   # Linux
   sudo systemctl start docker
   
   # Mac/Windows
   # Start Docker Desktop
   ```

### Platform-Specific Notes

#### Linux
- May need `sudo` for Docker commands
- Install `bc` calculator for cost calculations: `apt-get install bc`

#### Mac  
- Use Homebrew for dependencies: `brew install gcloud kubectl terraform`
- May need to install Xcode command line tools

#### Windows
- PowerShell execution policy may need adjustment:
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  ```
- WSL2 compatible for running shell scripts