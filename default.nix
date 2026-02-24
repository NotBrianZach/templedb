# TempleDB TUI - Nix Package Definition
# Creates a standalone executable with all dependencies bundled

{ pkgs ? import <nixpkgs> {} }:

let
  python = pkgs.python311;
  pythonPackages = python.pkgs;

  # Create a Python environment with all dependencies
  pythonEnv = python.withPackages (ps: with ps; [
    textual
    rich
    pyyaml  # For secret management YAML export
  ]);
in

pkgs.stdenv.mkDerivation {
  pname = "templedb-tui";
  version = "1.0.0";

  src = ./.;

  nativeBuildInputs = [ pkgs.makeWrapper ];

  # No build phase needed
  dontBuild = true;

  # Install phase
  installPhase = ''
    mkdir -p $out/bin
    mkdir -p $out/lib/templedb/src

    # Copy all source files
    cp -r src/*.py $out/lib/templedb/src/

    # Create wrapper script that uses the Python environment
    makeWrapper ${pythonEnv}/bin/python3 $out/bin/templedb-tui \
      --add-flags "$out/lib/templedb/src/tui.py" \
      --set PYTHONPATH "$out/lib/templedb/src"
  '';

  meta = with pkgs.lib; {
    description = "TempleDB Terminal User Interface";
    longDescription = ''
      Database-native project management with integrated TUI.
      Features:
      - Project and file management
      - Database-native VCS
      - Nix environment management
      - LLM context generation
      - Multi-file editing with emacs/tmux

      In honor of Terry A. Davis (1969-2018)
    '';
    license = licenses.mit;
    platforms = platforms.linux;
  };
}
