# Nix expression to build a standalone TempleDB TUI binary
# Creates a self-contained executable with all dependencies bundled
# No need to install Python or textual separately!

{ pkgs ? import <nixpkgs> {} }:

pkgs.python311.pkgs.buildPythonApplication {
  pname = "templedb-tui";
  version = "1.0.0";

  src = ./.;

  # Runtime dependencies
  propagatedBuildInputs = with pkgs.python311.pkgs; [
    textual
    rich
  ];

  # Don't run tests during build
  doCheck = false;

  # Install the TUI script
  installPhase = ''
    mkdir -p $out/bin
    mkdir -p $out/lib/templedb

    # Copy Python source files
    cp -r src/* $out/lib/templedb/

    # Create wrapper script
    cat > $out/bin/templedb-tui << 'EOF'
#!/usr/bin/env bash
# TempleDB TUI - Standalone binary (Nix-based)
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
export PYTHONPATH="$SCRIPT_DIR/../lib/templedb:$PYTHONPATH"
exec ${pkgs.python311}/bin/python3 "$SCRIPT_DIR/../lib/templedb/templedb_tui.py" "$@"
EOF

    chmod +x $out/bin/templedb-tui
  '';

  meta = with pkgs.lib; {
    description = "TempleDB Terminal User Interface - In Honor of Terry Davis";
    license = licenses.mit;
    platforms = platforms.linux;
  };
}
