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

            # SSL/Crypto
            openssl

            # Additional audio libraries
            alsa-lib
            pulseaudio
          ];

          shellHook = ''
            export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath [
              pkgs.portaudio
              pkgs.libsndfile
              pkgs.alsa-lib
              pkgs.openssl
              pkgs.stdenv.cc.cc.lib
            ]}:$LD_LIBRARY_PATH"

            echo "Pipecat development environment activated!"
            echo "Run 'uv init' to initialize project, then 'uv add pipecat-ai[daily,silero,openai]'"
          '';
        };
      }
    );
}
