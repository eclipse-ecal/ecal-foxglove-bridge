param(
    $eCALVersion = '5.11.3', #
    [ValidateSet('3.8', '3.9', '3.10', '3.11')]
    [string]$PythonVersion = '3.11'  # 3.8, 3.9, 3.10, 3.11
)

function eCALWheelName {
 $PyVersion =  $PythonVersion -replace '\.' , ''
 $WheelName = "ecal5-" + $eCALVersion + "-cp" + $PyVersion + "-cp" + $PyVersion + "-win_amd64.whl"
 return $WheelName 
}

function DownloadeCALPythonWheel {
  $WheelName = eCALWheelName
  $eCALTagName = "v" + $eCALVersion
  $DownloadCommand = "gh release download " + $eCALTagName + " -p " + $WheelName + " -R github.com/eclipse-ecal/ecal"
  Write-Build Green $DownloadCommand
  exec { Invoke-Expression $DownloadCommand }
}

function BuildDirName {
  $BuildDirName = "_build_eCAL_$($eCALVersion)_python_$($PythonVersion)"
  return $BuildDirName   
}

function ChangeDirectory {
  $BuildDir = BuildDirName
  New-Item -ItemType Directory -Path .\$BuildDir
  Set-Location -Path .\$BuildDir
}

# Synopsis: Create / Activate virtual environment
function ActivateEnvironment {
  if ( -not (Test-Path '.venv' ) )
  { 
    Write-Build Green 'Creating a virtual environment for the build'
    exec { py -$PythonVersion -m venv .venv }
  }
  Write-Build Green 'Activating virtual environment'
  .venv\Scripts\activate
}

function InstallRequirements {
  Write-Build Green 'Installing Requirements'
  exec { python --version }
  exec { python -m pip install -r ..\requirements.txt }
  DownloadeCALPythonWheel
  $WheelName = eCALWheelName
  exec { python -m pip install $WheelName }
  exec { python -m pip install pyinstaller }
}

# Synopsis: Deactivate virtual environment
function DeactivateEnvironment {
  exec { deactivate }
}

function BuildExe {
  Write-Build Green 'Building the installer'
  exec {pyinstaller ../ecal-foxglove-bridge.py --onefile}
}

task Build {
  ChangeDirectory
  ActivateEnvironment
  InstallRequirements
  BuildExe
  DeactivateEnvironment
}

task . Build