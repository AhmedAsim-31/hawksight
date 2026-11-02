# Install on Linux

These steps are untested; the macOS install is the tested path.
They should work on any distribution with systemd.
Without an NVIDIA or AMD GPU with 8 GB of memory or more, the model runs on the CPU and a review can take 20 minutes or longer.

1. Install the dependencies:

   ```sh
   curl -fsSL https://ollama.com/install.sh | sh   # Ollama
   npm install -g repomix                          # needs Node.js 18+
   python3 -m pip install --user requests huggingface_hub
   ```

   `git` and `openssl` come with most distributions.
   Check that Ollama is running with `ollama list`; if it is not, start it with `ollama serve` or see [Ollama's Linux docs](https://docs.ollama.com/linux).

2. Clone hawksight and build the model:

   ```sh
   git clone https://github.com/AhmedAsim-31/hawksight.git ~/hawksight
   cd ~/hawksight
   hf download bartowski/MiMo-V2.6-Distill-Qwen-9B-GGUF MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf --local-dir ~/.hawksight/models
   echo "FROM $HOME/.hawksight/models/MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf" > ~/.hawksight/models/Modelfile
   ollama create mimo-v2.6-distill-9b -f ~/.hawksight/models/Modelfile
   ollama create hawksight -f Modelfile
   ```

3. Create your GitHub App, then install it on your repositories from the link it prints:

   ```sh
   python3 create_app.py hawksight-<your-handle>
   ```

   On a machine without a browser, open `http://localhost:8765/` from a desktop through an SSH tunnel (`ssh -L 8765:localhost:8765 <host>`).

4. Run hawksight as a systemd user service:

   ```sh
   mkdir -p ~/.config/systemd/user
   cat > ~/.config/systemd/user/hawksight.service <<UNIT
   [Unit]
   Description=hawksight PR reviewer
   After=network-online.target

   [Service]
   ExecStart=$(command -v python3) $HOME/hawksight/listener.py
   Environment=PATH=$(dirname "$(command -v repomix)"):/usr/local/bin:/usr/bin:/bin
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=default.target
   UNIT
   systemctl --user daemon-reload
   systemctl --user enable --now hawksight
   loginctl enable-linger "$USER"   # keep it running after you log out
   ```

5. Follow the logs with `journalctl --user -u hawksight -f`.
   Restart after a code change with `systemctl --user restart hawksight`.
