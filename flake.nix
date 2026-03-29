{
  description = "Pipecat AI Development Environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            # Python & uv
            python312
            uv

            # Audio dependencies (required for pipecat voice)
            portaudio
            libsndfile
            ffmpeg

            # Build tools
            gcc
            pkg-config
            cmake
            git

            # SSL/Crypto
            openssl

            # Additional audio libraries
            alsa-lib
            pulseaudio

            # MuJoCo dependencies
            mujoco
            libGL
            libGLU
            glfw
            xorg.libX11
            xorg.libXi
            xorg.libXrandr
            xorg.libXcursor
            xorg.libXinerama
            mesa

            # Node.js for frontend
            nodejs_22
          ];

          shellHook = ''
            export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath [
              pkgs.portaudio
              pkgs.libsndfile
              pkgs.alsa-lib
              pkgs.openssl
              pkgs.stdenv.cc.cc.lib
              pkgs.libGL
              pkgs.libGLU
              pkgs.glfw
              pkgs.xorg.libX11
              pkgs.xorg.libXi
              pkgs.xorg.libXrandr
              pkgs.xorg.libXcursor
              pkgs.xorg.libXinerama
              pkgs.mesa
              pkgs.mujoco
            ]}:$LD_LIBRARY_PATH"

            echo "Pipecat development environment activated!"
            echo "Run 'uv sync' to install dependencies"
            echo "Run 'uv run server' to start the backend server"
          '';
        };
      }
    );
}
