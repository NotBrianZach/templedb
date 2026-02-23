{
  description = "projdb - SQLite-backed project config + sops secrets manager";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };

        # Rust toolchain
        # rust = pkgs.rustup;
      in
      {
        devShells.default = pkgs.mkShell {
          name = "projdb-dev";

          packages = with pkgs; [
            # rust
            # cargo
            # rust-analyzer

            # Native deps
            sqlite
            pkg-config

            # Runtime tools your CLI shells out to
            sops
            age

            # Nice-to-haves
            git
            just
          ];

          # Environment variables useful for dev
          shellHook = ''
            export RUST_BACKTRACE=1
            echo "projdb dev shell loaded"
          '';
        };
      });
}
