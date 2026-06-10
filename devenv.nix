{ pkgs, lib, config, inputs, ... }:

let
  cuda = pkgs.cudaPackages;
  cudaToolkit = cuda.cudatoolkit;
in
{
  dotenv = {
    enable = true;
  };

  packages = [
    cudaToolkit
    pkgs.ffmpeg
    pkgs.espeak-ng
  ];

  env = {
    CUDA_PATH = "${cudaToolkit}";
    CUDA_HOME = "${cudaToolkit}";
    # Triton/bitsandbytes: skip ldconfig (SIGSEGV in Nix) and use Nix gcc (host gcc SIGSEGV).
    TRITON_LIBCUDA_PATH = "/lib/x86_64-linux-gnu";
    CC = "${lib.getExe pkgs.stdenv.cc}";
    CXX = "${pkgs.stdenv.cc}/bin/c++";
    # Do not put Nix CUDA libs on LD_LIBRARY_PATH — PyTorch ships its own cuFFT/cuBLAS
    # wheels and mixing with Nix CUDA can break FFT ops (CUFFT_INTERNAL_ERROR).
  };

  tasks."cuda:preload".exec = ''
    site="$DEVENV_STATE/venv/lib/python3.13/site-packages"
    "$DEVENV_STATE/venv/bin/python" -c '
    import pathlib

    site = pathlib.Path("'$site'")
    (site / "_ai_home_lab_cuda_preload.py").write_text("""\
    \"\"\"Load the host NVIDIA driver without putting host libc on LD_LIBRARY_PATH.\"\"\"
    import ctypes
    from pathlib import Path

    for libcuda in (
        Path("/lib/x86_64-linux-gnu/libcuda.so.1"),
        Path("/usr/lib/x86_64-linux-gnu/libcuda.so.1"),
        Path("/run/opengl-driver/lib/libcuda.so.1"),
    ):
        if libcuda.exists():
            ctypes.CDLL(str(libcuda), mode=ctypes.RTLD_GLOBAL)
            break
    """)
    (site / "_ai_home_lab_cuda_preload.pth").write_text("import _ai_home_lab_cuda_preload\n")
    '
  '';
  tasks."cuda:preload".after = [ "devenv:python:uv" ];
  tasks."devenv:enterShell".after = [
    "cuda:preload"
    "jupyter:kernel"
  ];

  languages.python = {
    enable = true;
    manylinux.enable = true;
    uv = {
      enable = true;
      sync = {
        enable = true;
        # Main [project] deps always sync; add groups here (or set allGroups = true).
        groups = [ "dev" "epub-audiobook" ];
      };
    };
    venv.enable = true;
  };

  tasks."jupyter:kernel".exec = ''
    "$DEVENV_STATE/venv/bin/python" -m ipykernel install --sys-prefix \
      --name ai-home-lab \
      --display-name "ai-home-lab (devenv)"

    export TRITON_LIBCUDA_PATH=/lib/x86_64-linux-gnu
    export CC=${lib.getExe pkgs.stdenv.cc}
    export CXX=${pkgs.stdenv.cc}/bin/c++

    "$DEVENV_STATE/venv/bin/python" -c 'import json, os; from pathlib import Path; k = Path(os.environ["DEVENV_STATE"]) / "venv/share/jupyter/kernels/ai-home-lab/kernel.json"; d = json.loads(k.read_text()); d["env"] = {"TRITON_LIBCUDA_PATH": os.environ["TRITON_LIBCUDA_PATH"], "CC": os.environ["CC"], "CXX": os.environ["CXX"]}; k.write_text(json.dumps(d, indent=1) + chr(10))'
  '';
  tasks."jupyter:kernel".after = [ "cuda:preload" ];

  processes.agent-hub = {
    ports.http.allocate = 8001;
    exec = ''
      chainlit run agents/agent_hub/app.py \
        --host 0.0.0.0 \
        --port ${toString config.processes.agent-hub.ports.http.value}
    '';
  };

  scripts.run_agent_hub.exec = ''
    chainlit run agents/agent_hub/app.py --host 0.0.0.0 --port 8001
  '';

  enterShell = ''
    echo "Jupyter kernel: ai-home-lab (devenv)"
    echo "Agent hub: devenv up  (or run_agent_hub)"
  '';

  enterTest = ''
    echo "Running tests"
    git --version | grep --color=auto "${pkgs.git.version}"
  '';
}
