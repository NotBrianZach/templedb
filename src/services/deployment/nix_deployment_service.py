#!/usr/bin/env python3
"""
Nix Deployment Service - Phase 1 Implementation

Handles deployment of web services to VPS using Nix closures and systemd.
"""
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import tempfile
import shutil

from logger import get_logger

logger = get_logger(__name__)


@dataclass
class NixDeploymentResult:
    """Result of a Nix deployment operation"""
    success: bool
    message: str
    closure_path: Optional[Path] = None
    systemd_unit: Optional[str] = None
    service_url: Optional[str] = None
    error: Optional[str] = None
    flake_path: Optional[Path] = None
    package_installed: bool = False


class NixDeploymentService:
    """
    Service for deploying projects using Nix closures.

    Workflow:
    1. Build Nix closure from project
    2. Transfer closure to target VPS
    3. Import closure on target
    4. Generate systemd unit file
    5. Enable and start service
    6. Run health checks
    """

    def __init__(self, db_connection=None):
        self.db = db_connection
        self.temp_dir = Path(tempfile.gettempdir()) / "templedb-deploy"
        self.temp_dir.mkdir(exist_ok=True)

    def build_nix_closure(self, project_path: Path, project_slug: str) -> NixDeploymentResult:
        """
        Build Nix closure for project.

        Args:
            project_path: Path to project directory
            project_slug: Project identifier

        Returns:
            NixDeploymentResult with closure path
        """
        logger.info(f"Building Nix closure for {project_slug}")

        # Check if project has flake.nix
        flake_path = project_path / "flake.nix"
        if not flake_path.exists():
            # Generate flake.nix if missing
            logger.info("No flake.nix found, generating default configuration")
            self._generate_default_flake(project_path, project_slug)

        try:
            # Build the Nix package
            logger.info("Running: nix build")
            result = subprocess.run(
                ["nix", "build", "--out-link", f"{self.temp_dir}/result-{project_slug}"],
                cwd=project_path,
                capture_output=True,
                text=True,
                check=True
            )

            result_link = self.temp_dir / f"result-{project_slug}"

            # Export Nix closure
            closure_path = self.temp_dir / f"{project_slug}-closure"
            closure_path.mkdir(exist_ok=True)

            logger.info("Exporting Nix closure")

            # Get all store paths needed
            store_paths_result = subprocess.run(
                ["nix-store", "-qR", str(result_link)],
                capture_output=True,
                text=True,
                check=True
            )

            store_paths = store_paths_result.stdout.strip().split('\n')
            logger.info(f"Closure contains {len(store_paths)} store paths")

            # Export to NAR archive
            nar_path = closure_path / "closure.nar"
            with open(nar_path, 'wb') as f:
                subprocess.run(
                    ["nix-store", "--export"] + store_paths,
                    stdout=f,
                    check=True
                )

            # Create metadata file
            metadata = {
                "project": project_slug,
                "store_paths": store_paths,
                "main_executable": str(result_link),
                "build_time": subprocess.check_output(["date", "+%Y-%m-%dT%H:%M:%S"]).decode().strip()
            }

            with open(closure_path / "metadata.json", 'w') as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"Nix closure exported to {closure_path}")

            return NixDeploymentResult(
                success=True,
                message=f"Nix closure built successfully ({len(store_paths)} paths)",
                closure_path=closure_path
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Nix build failed: {e.stderr}")
            return NixDeploymentResult(
                success=False,
                message="Nix build failed",
                error=e.stderr
            )
        except Exception as e:
            logger.error(f"Unexpected error during Nix build: {e}")
            return NixDeploymentResult(
                success=False,
                message="Nix build failed",
                error=str(e)
            )

    def _generate_default_flake(self, project_path: Path, project_slug: str):
        """Generate a default flake.nix for a Python/Node project"""

        # Detect project type
        if (project_path / "package.json").exists():
            # Node.js project
            flake_content = self._generate_nodejs_flake(project_slug)
        elif (project_path / "requirements.txt").exists() or (project_path / "pyproject.toml").exists():
            # Python project
            flake_content = self._generate_python_flake(project_slug)
        else:
            raise ValueError("Cannot determine project type (no package.json, requirements.txt, or pyproject.toml found)")

        with open(project_path / "flake.nix", 'w') as f:
            f.write(flake_content)

        logger.info(f"Generated flake.nix for {project_slug}")

    def _generate_python_flake(self, project_slug: str) -> str:
        """Generate flake.nix for Python project"""
        return f'''{{
  description = "{project_slug} - Python service";

  inputs = {{
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  }};

  outputs = {{ self, nixpkgs }}: {{
    packages.x86_64-linux.default =
      let
        pkgs = nixpkgs.legacyPackages.x86_64-linux;
      in pkgs.python311Packages.buildPythonApplication {{
        pname = "{project_slug}";
        version = "1.0.0";
        src = ./.;

        propagatedBuildInputs = with pkgs.python311Packages; [
          # Add your Python dependencies here
          # Example: fastapi uvicorn sqlalchemy psycopg2
        ];

        # If you have a requirements.txt
        # format = "other";
        # propagatedBuildInputs = with pkgs.python311Packages; (
        #   builtins.map (name: pkgs.python311Packages.${{name}})
        #   (builtins.filter (x: x != "") (pkgs.lib.splitString "\\n" (builtins.readFile ./requirements.txt)))
        # );
      }};
  }};
}}
'''

    def _generate_nodejs_flake(self, project_slug: str) -> str:
        """Generate flake.nix for Node.js project"""
        return f'''{{
  description = "{project_slug} - Node.js service";

  inputs = {{
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  }};

  outputs = {{ self, nixpkgs }}: {{
    packages.x86_64-linux.default =
      let
        pkgs = nixpkgs.legacyPackages.x86_64-linux;
      in pkgs.buildNpmPackage {{
        pname = "{project_slug}";
        version = "1.0.0";
        src = ./.;

        npmDepsHash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
        # After first build, replace with actual hash from error message

        installPhase = ''
          mkdir -p $out/bin
          cp -r . $out/
          makeWrapper ${{pkgs.nodejs}}/bin/node $out/bin/{project_slug} \\
            --add-flags "$out/dist/index.js"
        '';

        buildInputs = [ pkgs.makeWrapper ];
      }};
  }};
}}
'''

    def transfer_closure(
        self,
        closure_path: Path,
        target_host: str,
        target_user: str = "deploy"
    ) -> NixDeploymentResult:
        """
        Transfer Nix closure to target VPS via scp.

        Args:
            closure_path: Path to closure directory
            target_host: Target hostname or IP
            target_user: SSH user on target

        Returns:
            NixDeploymentResult
        """
        logger.info(f"Transferring closure to {target_user}@{target_host}")

        try:
            # Create remote directory
            subprocess.run(
                ["ssh", f"{target_user}@{target_host}", "mkdir", "-p", "/opt/templedb-deployments"],
                check=True
            )

            # Transfer closure
            remote_path = f"{target_user}@{target_host}:/opt/templedb-deployments/"

            logger.info(f"Copying {closure_path} to {remote_path}")
            subprocess.run(
                ["scp", "-r", str(closure_path), remote_path],
                check=True
            )

            return NixDeploymentResult(
                success=True,
                message=f"Closure transferred to {target_host}"
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Transfer failed: {e}")
            return NixDeploymentResult(
                success=False,
                message="Closure transfer failed",
                error=str(e)
            )

    def import_closure(
        self,
        closure_name: str,
        target_host: str,
        target_user: str = "deploy"
    ) -> NixDeploymentResult:
        """
        Import Nix closure on target VPS.

        Args:
            closure_name: Name of closure directory
            target_host: Target hostname
            target_user: SSH user

        Returns:
            NixDeploymentResult
        """
        logger.info(f"Importing closure on {target_host}")

        try:
            # Import NAR archive into Nix store
            import_cmd = f"nix-store --import < /opt/templedb-deployments/{closure_name}/closure.nar"

            result = subprocess.run(
                ["ssh", f"{target_user}@{target_host}", import_cmd],
                capture_output=True,
                text=True,
                check=True
            )

            logger.info(f"Closure imported successfully")

            return NixDeploymentResult(
                success=True,
                message="Closure imported on target"
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Import failed: {e.stderr}")
            return NixDeploymentResult(
                success=False,
                message="Closure import failed",
                error=e.stderr
            )

    def generate_systemd_unit(
        self,
        project_slug: str,
        executable_path: str,
        port: int = 8000,
        env_vars: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Generate systemd unit file for service.

        Args:
            project_slug: Project identifier
            executable_path: Path to service executable
            port: Port to listen on
            env_vars: Environment variables

        Returns:
            systemd unit file content
        """
        env_vars = env_vars or {}

        # Generate EnvironmentFile
        env_file_content = "\n".join([
            f"{key}={value}"
            for key, value in env_vars.items()
        ])

        # systemd unit template
        unit_content = f"""[Unit]
Description={project_slug} - TempleDB Deployment
After=network.target

[Service]
Type=notify
User={project_slug}
Group={project_slug}
WorkingDirectory=/opt/{project_slug}

# Environment
EnvironmentFile=-/etc/{project_slug}/secrets.env
Environment="PORT={port}"

# Executable (from Nix store)
ExecStart={executable_path}

# Restart policy
Restart=always
RestartSec=10

# Resource limits
MemoryMax=1G
CPUQuota=200%

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/{project_slug}
ReadWritePaths=/var/log/{project_slug}

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier={project_slug}

[Install]
WantedBy=multi-user.target
"""

        return unit_content

    def activate_service(
        self,
        project_slug: str,
        systemd_unit: str,
        target_host: str,
        target_user: str = "deploy"
    ) -> NixDeploymentResult:
        """
        Activate systemd service on target.

        Args:
            project_slug: Project identifier
            systemd_unit: systemd unit file content
            target_host: Target hostname
            target_user: SSH user

        Returns:
            NixDeploymentResult
        """
        logger.info(f"Activating service on {target_host}")

        try:
            # Write systemd unit file
            unit_path = f"/etc/systemd/system/{project_slug}.service"

            # Create temporary file with unit content
            temp_unit = self.temp_dir / f"{project_slug}.service"
            with open(temp_unit, 'w') as f:
                f.write(systemd_unit)

            # Copy to target
            subprocess.run(
                ["scp", str(temp_unit), f"{target_user}@{target_host}:/tmp/{project_slug}.service"],
                check=True
            )

            # Move to systemd directory (requires sudo)
            subprocess.run(
                ["ssh", f"{target_user}@{target_host}",
                 f"sudo mv /tmp/{project_slug}.service {unit_path}"],
                check=True
            )

            # Reload systemd
            subprocess.run(
                ["ssh", f"{target_user}@{target_host}", "sudo systemctl daemon-reload"],
                check=True
            )

            # Enable service
            subprocess.run(
                ["ssh", f"{target_user}@{target_host}", f"sudo systemctl enable {project_slug}"],
                check=True
            )

            # Start service
            subprocess.run(
                ["ssh", f"{target_user}@{target_host}", f"sudo systemctl start {project_slug}"],
                check=True
            )

            logger.info(f"Service activated successfully")

            return NixDeploymentResult(
                success=True,
                message=f"Service {project_slug} is now running",
                systemd_unit=systemd_unit
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Service activation failed: {e}")
            return NixDeploymentResult(
                success=False,
                message="Service activation failed",
                error=str(e)
            )

    def health_check(
        self,
        target_host: str,
        port: int = 8000,
        endpoint: str = "/health"
    ) -> Tuple[bool, str]:
        """
        Run health check against deployed service.

        Args:
            target_host: Target hostname
            port: Service port
            endpoint: Health check endpoint

        Returns:
            (success, message) tuple
        """
        logger.info(f"Running health check on {target_host}:{port}{endpoint}")

        try:
            # Use curl via SSH
            result = subprocess.run(
                ["ssh", f"deploy@{target_host}",
                 f"curl -f http://localhost:{port}{endpoint}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True
            )

            logger.info("Health check passed")
            return (True, "Service is healthy")

        except subprocess.TimeoutExpired:
            return (False, "Health check timed out")
        except subprocess.CalledProcessError as e:
            return (False, f"Health check failed: {e.stderr}")
        except Exception as e:
            return (False, f"Health check error: {str(e)}")

    def full_deployment(
        self,
        project_path: Path,
        project_slug: str,
        target_host: str,
        target_user: str = "deploy",
        port: int = 8000,
        env_vars: Optional[Dict[str, str]] = None
    ) -> NixDeploymentResult:
        """
        Execute full deployment workflow.

        Steps:
        1. Build Nix closure
        2. Transfer to target
        3. Import on target
        4. Generate systemd unit
        5. Activate service
        6. Run health check

        Args:
            project_path: Path to project
            project_slug: Project identifier
            target_host: Target VPS hostname
            target_user: SSH user
            port: Service port
            env_vars: Environment variables

        Returns:
            NixDeploymentResult
        """
        logger.info(f"Starting full deployment for {project_slug} to {target_host}")

        # Step 1: Build closure
        build_result = self.build_nix_closure(project_path, project_slug)
        if not build_result.success:
            return build_result

        # Step 2: Transfer closure
        transfer_result = self.transfer_closure(
            build_result.closure_path,
            target_host,
            target_user
        )
        if not transfer_result.success:
            return transfer_result

        # Step 3: Import closure
        closure_name = build_result.closure_path.name
        import_result = self.import_closure(closure_name, target_host, target_user)
        if not import_result.success:
            return import_result

        # Step 4: Read metadata to get executable path
        metadata_path = build_result.closure_path / "metadata.json"
        with open(metadata_path) as f:
            metadata = json.load(f)

        executable_path = metadata['main_executable']

        # Step 5: Generate systemd unit
        systemd_unit = self.generate_systemd_unit(
            project_slug,
            executable_path,
            port,
            env_vars
        )

        # Step 6: Activate service
        activate_result = self.activate_service(
            project_slug,
            systemd_unit,
            target_host,
            target_user
        )
        if not activate_result.success:
            return activate_result

        # Step 7: Health check (wait a moment for service to start)
        import time
        time.sleep(5)

        health_ok, health_msg = self.health_check(target_host, port)

        if health_ok:
            return NixDeploymentResult(
                success=True,
                message=f"Deployment complete! Service is running at http://{target_host}:{port}",
                systemd_unit=systemd_unit,
                service_url=f"http://{target_host}:{port}"
            )
        else:
            logger.warning(f"Service deployed but health check failed: {health_msg}")
            return NixDeploymentResult(
                success=True,  # Still successful deployment, just health check failed
                message=f"Service deployed, but health check failed: {health_msg}",
                systemd_unit=systemd_unit,
                error=health_msg
            )

    # ========================================================================
    # CLI Tool Packaging (for Nix packages/flakes)
    # ========================================================================

    def generate_cli_flake(
        self,
        project_path: Path,
        project_slug: str,
        description: Optional[str] = None,
        version: str = "1.0.0"
    ) -> NixDeploymentResult:
        """
        Generate a Nix flake for a CLI tool that can be installed as a package.

        This generates a flake.nix that:
        - Builds the CLI tool as a Nix package
        - Can be installed with `nix profile install`
        - Can be added to system configuration
        - Works with `nix run`

        Args:
            project_path: Path to CLI tool project
            project_slug: Project identifier
            description: Project description
            version: Version string

        Returns:
            NixDeploymentResult with flake path
        """
        logger.info(f"Generating CLI tool flake for {project_slug}")

        # Detect project type
        if (project_path / "package.json").exists():
            flake_content = self._generate_cli_nodejs_flake(project_slug, description, version)
        elif (project_path / "requirements.txt").exists() or (project_path / "pyproject.toml").exists():
            flake_content = self._generate_cli_python_flake(project_slug, description, version)
        elif (project_path / "Cargo.toml").exists():
            flake_content = self._generate_cli_rust_flake(project_slug, description, version)
        else:
            return NixDeploymentResult(
                success=False,
                message="Cannot determine project type",
                error="No package.json, requirements.txt, pyproject.toml, or Cargo.toml found"
            )

        flake_path = project_path / "flake.nix"

        # Backup existing flake if present
        if flake_path.exists():
            backup_path = project_path / "flake.nix.backup"
            shutil.copy(flake_path, backup_path)
            logger.info(f"Backed up existing flake.nix to {backup_path}")

        # Write new flake
        with open(flake_path, 'w') as f:
            f.write(flake_content)

        logger.info(f"Generated flake.nix at {flake_path}")

        return NixDeploymentResult(
            success=True,
            message=f"CLI flake generated successfully",
            flake_path=flake_path
        )

    def _generate_cli_python_flake(self, project_slug: str, description: Optional[str], version: str) -> str:
        """Generate flake.nix for Python CLI tool"""
        desc = description or f"{project_slug} - Python CLI tool"
        return f'''{{
  description = "{desc}";

  inputs = {{
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  }};

  outputs = {{ self, nixpkgs, flake-utils }}:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${{system}};
      in
      {{
        packages.default = pkgs.python3Packages.buildPythonApplication {{
          pname = "{project_slug}";
          version = "{version}";
          src = ./.;

          format = "pyproject";  # or "setuptools" if using setup.py

          propagatedBuildInputs = with pkgs.python3Packages; [
            # Add your Python dependencies here
            # Example: click requests pyyaml
          ];

          # If you have a requirements.txt, you can use:
          # nativeBuildInputs = [ pkgs.python3Packages.pip ];
          # buildInputs = with pkgs.python3Packages; [
          #   # dependencies from requirements.txt
          # ];

          meta = with pkgs.lib; {{
            description = "{desc}";
            homepage = "https://github.com/yourorg/{project_slug}";
            license = licenses.mit;
            maintainers = [ ];
          }};
        }};

        # Allow running with `nix run`
        apps.default = {{
          type = "app";
          program = "${{self.packages.${{system}}.default}}/bin/{project_slug}";
        }};

        # Development shell
        devShells.default = pkgs.mkShell {{
          buildInputs = with pkgs; [
            python3
            python3Packages.pip
            python3Packages.setuptools
          ];
        }};
      }}
    );
}}
'''

    def _generate_cli_nodejs_flake(self, project_slug: str, description: Optional[str], version: str) -> str:
        """Generate flake.nix for Node.js CLI tool"""
        desc = description or f"{project_slug} - Node.js CLI tool"
        return f'''{{
  description = "{desc}";

  inputs = {{
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  }};

  outputs = {{ self, nixpkgs, flake-utils }}:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${{system}};
      in
      {{
        packages.default = pkgs.buildNpmPackage {{
          pname = "{project_slug}";
          version = "{version}";
          src = ./.;

          npmDepsHash = "";  # Run `nix build` once to get the hash

          # If using package-lock.json v3
          # npmDepsHash = pkgs.lib.fakeSha256;

          meta = with pkgs.lib; {{
            description = "{desc}";
            homepage = "https://github.com/yourorg/{project_slug}";
            license = licenses.mit;
            maintainers = [ ];
          }};
        }};

        # Allow running with `nix run`
        apps.default = {{
          type = "app";
          program = "${{self.packages.${{system}}.default}}/bin/{project_slug}";
        }};

        # Development shell
        devShells.default = pkgs.mkShell {{
          buildInputs = with pkgs; [
            nodejs
            nodePackages.npm
          ];
        }};
      }}
    );
}}
'''

    def _generate_cli_rust_flake(self, project_slug: str, description: Optional[str], version: str) -> str:
        """Generate flake.nix for Rust CLI tool"""
        desc = description or f"{project_slug} - Rust CLI tool"
        return f'''{{
  description = "{desc}";

  inputs = {{
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    rust-overlay.url = "github:oxalica/rust-overlay";
  }};

  outputs = {{ self, nixpkgs, flake-utils, rust-overlay }}:
    flake-utils.lib.eachDefaultSystem (system:
      let
        overlays = [ (import rust-overlay) ];
        pkgs = import nixpkgs {{
          inherit system overlays;
        }};
      in
      {{
        packages.default = pkgs.rustPlatform.buildRustPackage {{
          pname = "{project_slug}";
          version = "{version}";
          src = ./.;

          cargoLock = {{
            lockFile = ./Cargo.lock;
          }};

          meta = with pkgs.lib; {{
            description = "{desc}";
            homepage = "https://github.com/yourorg/{project_slug}";
            license = licenses.mit;
            maintainers = [ ];
          }};
        }};

        # Allow running with `nix run`
        apps.default = {{
          type = "app";
          program = "${{self.packages.${{system}}.default}}/bin/{project_slug}";
        }};

        # Development shell
        devShells.default = pkgs.mkShell {{
          buildInputs = with pkgs; [
            rust-bin.stable.latest.default
            cargo
            rustc
          ];
        }};
      }}
    );
}}
'''

    def install_local(
        self,
        project_path: Path,
        project_slug: str
    ) -> NixDeploymentResult:
        """
        Install CLI tool to local Nix profile.

        Uses `nix profile install` to install the package locally.
        The tool will be available in PATH after installation.

        Args:
            project_path: Path to CLI tool project
            project_slug: Project identifier

        Returns:
            NixDeploymentResult
        """
        logger.info(f"Installing {project_slug} to local Nix profile")

        # Check if flake.nix exists
        flake_path = project_path / "flake.nix"
        if not flake_path.exists():
            return NixDeploymentResult(
                success=False,
                message="No flake.nix found. Run generate-flake first.",
                error="Missing flake.nix"
            )

        try:
            # Install to profile
            logger.info(f"Running: nix profile install {project_path}")
            result = subprocess.run(
                ["nix", "profile", "install", str(project_path)],
                capture_output=True,
                text=True,
                check=True
            )

            logger.info(f"Successfully installed {project_slug} to local profile")

            return NixDeploymentResult(
                success=True,
                message=f"{project_slug} installed to local Nix profile",
                package_installed=True
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Installation failed: {e.stderr}")
            return NixDeploymentResult(
                success=False,
                message="Installation failed",
                error=e.stderr
            )
        except Exception as e:
            logger.error(f"Unexpected error during installation: {e}")
            return NixDeploymentResult(
                success=False,
                message="Installation failed",
                error=str(e)
            )

    def add_to_system_config(
        self,
        project_path: Path,
        project_slug: str,
        config_path: Optional[Path] = None
    ) -> NixDeploymentResult:
        """
        Add CLI tool to NixOS system configuration.

        This generates the Nix expression to add to configuration.nix
        or home-manager configuration.

        Args:
            project_path: Path to CLI tool project
            project_slug: Project identifier
            config_path: Path to configuration.nix (auto-detected if None)

        Returns:
            NixDeploymentResult with instructions
        """
        logger.info(f"Generating system config entry for {project_slug}")

        # Check if flake.nix exists
        flake_path = project_path / "flake.nix"
        if not flake_path.exists():
            return NixDeploymentResult(
                success=False,
                message="No flake.nix found. Run generate-flake first.",
                error="Missing flake.nix"
            )

        # Generate configuration snippet
        config_snippet = f'''
# Add to your configuration.nix or home.nix

{{
  inputs = {{
    {project_slug}.url = "path:{project_path}";
    # or for git repository:
    # {project_slug}.url = "github:yourorg/{project_slug}";
  }};

  outputs = {{ self, nixpkgs, {project_slug}, ... }}: {{
    # For NixOS system configuration:
    nixosConfigurations.yourhost = nixpkgs.lib.nixosSystem {{
      modules = [
        {{
          environment.systemPackages = [
            {project_slug}.packages.x86_64-linux.default
          ];
        }}
      ];
    }};

    # For home-manager:
    homeConfigurations.youruser = home-manager.lib.homeManagerConfiguration {{
      modules = [
        {{
          home.packages = [
            {project_slug}.packages.x86_64-linux.default
          ];
        }}
      ];
    }};
  }};
}}

# Or add directly to environment.systemPackages:
# environment.systemPackages = with pkgs; [
#   (import {project_path} {{ inherit system; }}).packages.${{system}}.default
# ];
'''

        # Write to temp file
        snippet_file = self.temp_dir / f"{project_slug}-system-config.nix"
        with open(snippet_file, 'w') as f:
            f.write(config_snippet)

        logger.info(f"Configuration snippet written to {snippet_file}")

        return NixDeploymentResult(
            success=True,
            message=f"System configuration snippet generated at {snippet_file}",
            flake_path=snippet_file
        )
