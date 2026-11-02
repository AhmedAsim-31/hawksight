# Install on Windows

These steps are untested; the macOS install is the tested path.
They need Windows 10 22H2 or newer.
Without an NVIDIA or AMD GPU with 8 GB of memory or more, the model runs on the CPU and a review can take 20 minutes or longer.

Run the commands in PowerShell.

1. Install the dependencies:
   - [Ollama](https://ollama.com/download/windows) with `OllamaSetup.exe`. It runs in the background after install.
   - [Python 3](https://www.python.org/downloads/windows/), with "Add python.exe to PATH" ticked.
   - [Git for Windows](https://git-scm.com/download/win). It includes `openssl`, which hawksight uses to sign its GitHub App token.
   - [Node.js](https://nodejs.org) 18 or newer.

   Then:

   ```powershell
   npm install -g repomix
   python -m pip install --user requests huggingface_hub
   # openssl ships inside Git for Windows; put it on your PATH:
   [Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\Program Files\Git\usr\bin", "User")
   ```

   Open a new PowerShell window so the PATH change applies.

2. Clone hawksight and build the model:

   ```powershell
   git clone https://github.com/AhmedAsim-31/hawksight.git $HOME\hawksight
   cd $HOME\hawksight
   hf download bartowski/MiMo-V2.6-Distill-Qwen-9B-GGUF MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf --local-dir $HOME\.hawksight\models
   "FROM $HOME\.hawksight\models\MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf" | Out-File -Encoding ascii $HOME\.hawksight\models\Modelfile
   ollama create mimo-v2.6-distill-9b -f $HOME\.hawksight\models\Modelfile
   ollama create hawksight -f Modelfile
   ```

3. Create your GitHub App, then install it on your repositories from the link it prints:

   ```powershell
   python create_app.py hawksight-<your-handle>
   ```

4. Start hawksight at logon, with no console window, as a scheduled task:

   ```powershell
   $pythonw = (Get-Command pythonw).Source
   $action = New-ScheduledTaskAction -Execute $pythonw -WorkingDirectory "$HOME\hawksight" `
     -Argument "`"$HOME\hawksight\listener.py`" `"$HOME\.hawksight\hawksight.log`""
   $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
   $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -RestartCount 999 `
     -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
   Register-ScheduledTask -TaskName hawksight -Action $action -Trigger $trigger -Settings $settings
   Start-ScheduledTask -TaskName hawksight
   ```

5. Follow the logs with `Get-Content $HOME\.hawksight\hawksight.log -Wait`.
   Restart after a code change with `Stop-ScheduledTask hawksight; Start-ScheduledTask hawksight`.
