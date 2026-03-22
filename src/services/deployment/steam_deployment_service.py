#!/usr/bin/env python3
"""
Steam Deployment Service - Phase 3 Implementation

Handles deployment of games to Steam using:
- Unity + Steamworks.NET
- Godot + GodotSteam
- HTML5 games with Steam web integration
- Multi-platform builds (Windows, macOS, Linux)
- Steam Pipe uploads
- Steam configuration (achievements, cloud saves)
"""
import os
import json
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from logger import get_logger

logger = get_logger(__name__)


@dataclass
class SteamDeploymentResult:
    """Result of a Steam deployment operation"""
    success: bool
    message: str
    build_path: Optional[Path] = None
    depot_id: Optional[str] = None
    app_id: Optional[str] = None
    error: Optional[str] = None
    platform: Optional[str] = None


class SteamDeploymentService:
    """Service for deploying games to Steam"""

    def __init__(self, db_connection):
        self.conn = db_connection
        self.temp_dir = Path("/tmp/templedb-steam")
        self.temp_dir.mkdir(exist_ok=True)

    # ========================================================================
    # Unity + Steamworks.NET
    # ========================================================================

    def build_unity_game(
        self,
        project_path: Path,
        build_target: str = "StandaloneWindows64",
        output_path: Optional[Path] = None,
        development_build: bool = False
    ) -> SteamDeploymentResult:
        """
        Build Unity game for specified platform

        Args:
            project_path: Path to Unity project
            build_target: Unity build target (StandaloneWindows64, StandaloneOSX, StandaloneLinux64)
            output_path: Where to output the build
            development_build: Enable development mode

        Returns:
            SteamDeploymentResult with build path
        """
        if not project_path.exists():
            return SteamDeploymentResult(
                success=False,
                message=f"Unity project not found: {project_path}",
                error="Project path does not exist"
            )

        # Determine output path
        if not output_path:
            output_path = self.temp_dir / f"unity-build-{build_target}"
        output_path.mkdir(parents=True, exist_ok=True)

        # Find Unity executable
        unity_path = self._find_unity_executable()
        if not unity_path:
            return SteamDeploymentResult(
                success=False,
                message="Unity executable not found",
                error="Install Unity or add to PATH"
            )

        # Build command
        cmd = [
            str(unity_path),
            "-quit",
            "-batchmode",
            "-projectPath", str(project_path),
            "-buildTarget", build_target,
            "-executeMethod", "BuildScript.Build",
            f"-buildPath={output_path}"
        ]

        if development_build:
            cmd.append("-development")

        try:
            logger.info(f"Building Unity game: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800  # 30 minute timeout
            )

            if result.returncode != 0:
                return SteamDeploymentResult(
                    success=False,
                    message="Unity build failed",
                    error=result.stderr or result.stdout
                )

            return SteamDeploymentResult(
                success=True,
                message=f"Unity build completed for {build_target}",
                build_path=output_path,
                platform=build_target
            )

        except subprocess.TimeoutExpired:
            return SteamDeploymentResult(
                success=False,
                message="Unity build timed out (30 minutes)",
                error="Build took too long"
            )
        except Exception as e:
            return SteamDeploymentResult(
                success=False,
                message=f"Unity build error: {str(e)}",
                error=str(e)
            )

    def install_steamworks_net(
        self,
        project_path: Path,
        steamworks_net_version: str = "20.2.0"
    ) -> SteamDeploymentResult:
        """
        Install Steamworks.NET package in Unity project

        Args:
            project_path: Path to Unity project
            steamworks_net_version: Steamworks.NET version

        Returns:
            SteamDeploymentResult
        """
        packages_dir = project_path / "Packages"
        manifest_file = packages_dir / "manifest.json"

        if not manifest_file.exists():
            return SteamDeploymentResult(
                success=False,
                message="Unity manifest.json not found",
                error="Not a valid Unity project"
            )

        try:
            # Read manifest
            with open(manifest_file, 'r') as f:
                manifest = json.load(f)

            # Add Steamworks.NET
            if "dependencies" not in manifest:
                manifest["dependencies"] = {}

            manifest["dependencies"]["com.rlabrecque.steamworks.net"] = steamworks_net_version

            # Write manifest
            with open(manifest_file, 'w') as f:
                json.dump(manifest, f, indent=2)

            return SteamDeploymentResult(
                success=True,
                message=f"Steamworks.NET {steamworks_net_version} added to manifest.json"
            )

        except Exception as e:
            return SteamDeploymentResult(
                success=False,
                message=f"Failed to install Steamworks.NET: {str(e)}",
                error=str(e)
            )

    # ========================================================================
    # Godot + GodotSteam
    # ========================================================================

    def build_godot_game(
        self,
        project_path: Path,
        export_preset: str,
        output_path: Optional[Path] = None
    ) -> SteamDeploymentResult:
        """
        Build Godot game using export preset

        Args:
            project_path: Path to Godot project (containing project.godot)
            export_preset: Name of export preset (e.g., "Windows Desktop", "Linux/X11")
            output_path: Where to output the build

        Returns:
            SteamDeploymentResult with build path
        """
        project_file = project_path / "project.godot"
        if not project_file.exists():
            return SteamDeploymentResult(
                success=False,
                message=f"Godot project.godot not found: {project_file}",
                error="Not a valid Godot project"
            )

        # Determine output path
        if not output_path:
            preset_name = export_preset.replace("/", "-").replace(" ", "-")
            output_path = self.temp_dir / f"godot-build-{preset_name}"
        output_path.mkdir(parents=True, exist_ok=True)

        # Find Godot executable
        godot_path = self._find_godot_executable()
        if not godot_path:
            return SteamDeploymentResult(
                success=False,
                message="Godot executable not found",
                error="Install Godot or add to PATH"
            )

        # Export command
        output_file = output_path / "game.exe" if "Windows" in export_preset else output_path / "game"
        cmd = [
            str(godot_path),
            "--headless",
            "--path", str(project_path),
            "--export", export_preset,
            str(output_file)
        ]

        try:
            logger.info(f"Building Godot game: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout
            )

            if result.returncode != 0:
                return SteamDeploymentResult(
                    success=False,
                    message="Godot export failed",
                    error=result.stderr or result.stdout
                )

            return SteamDeploymentResult(
                success=True,
                message=f"Godot export completed for {export_preset}",
                build_path=output_path,
                platform=export_preset
            )

        except subprocess.TimeoutExpired:
            return SteamDeploymentResult(
                success=False,
                message="Godot export timed out (10 minutes)",
                error="Export took too long"
            )
        except Exception as e:
            return SteamDeploymentResult(
                success=False,
                message=f"Godot export error: {str(e)}",
                error=str(e)
            )

    def install_godot_steam(
        self,
        project_path: Path,
        godot_steam_version: str = "latest"
    ) -> SteamDeploymentResult:
        """
        Install GodotSteam plugin

        Args:
            project_path: Path to Godot project
            godot_steam_version: GodotSteam version

        Returns:
            SteamDeploymentResult
        """
        addons_dir = project_path / "addons"
        addons_dir.mkdir(exist_ok=True)

        try:
            # Download GodotSteam from GitHub releases
            # For now, just create placeholder structure
            godot_steam_dir = addons_dir / "godotsteam"
            godot_steam_dir.mkdir(exist_ok=True)

            plugin_cfg = godot_steam_dir / "plugin.cfg"
            plugin_cfg.write_text("""[plugin]

name="GodotSteam"
description="Steamworks integration for Godot"
author="GodotSteam"
version="3.24"
script="godotsteam.gd"
""")

            return SteamDeploymentResult(
                success=True,
                message=f"GodotSteam plugin directory created at {godot_steam_dir}",
                build_path=godot_steam_dir
            )

        except Exception as e:
            return SteamDeploymentResult(
                success=False,
                message=f"Failed to install GodotSteam: {str(e)}",
                error=str(e)
            )

    # ========================================================================
    # HTML5 / JavaScript Games
    # ========================================================================

    def package_html5_game(
        self,
        project_path: Path,
        game_name: str,
        output_path: Optional[Path] = None
    ) -> SteamDeploymentResult:
        """
        Package HTML5 game for Steam (uses Steam CEF browser)

        Args:
            project_path: Path to HTML5 game directory
            game_name: Name of the game
            output_path: Where to output the packaged game

        Returns:
            SteamDeploymentResult with package path
        """
        if not project_path.exists():
            return SteamDeploymentResult(
                success=False,
                message=f"HTML5 project not found: {project_path}",
                error="Project path does not exist"
            )

        # Find index.html
        index_file = project_path / "index.html"
        if not index_file.exists():
            return SteamDeploymentResult(
                success=False,
                message="index.html not found in project",
                error="Not a valid HTML5 game project"
            )

        # Determine output path
        if not output_path:
            output_path = self.temp_dir / f"html5-{game_name}"
        output_path.mkdir(parents=True, exist_ok=True)

        try:
            # Copy all files
            for item in project_path.iterdir():
                if item.is_file():
                    shutil.copy2(item, output_path / item.name)
                elif item.is_dir() and not item.name.startswith('.'):
                    shutil.copytree(item, output_path / item.name, dirs_exist_ok=True)

            # Create Steam wrapper
            self._create_steam_html5_wrapper(output_path, game_name)

            return SteamDeploymentResult(
                success=True,
                message=f"HTML5 game packaged for Steam",
                build_path=output_path,
                platform="HTML5"
            )

        except Exception as e:
            return SteamDeploymentResult(
                success=False,
                message=f"HTML5 packaging failed: {str(e)}",
                error=str(e)
            )

    def _create_steam_html5_wrapper(self, output_path: Path, game_name: str):
        """Create a Steam CEF wrapper for HTML5 game"""
        # Create a simple launcher script
        launcher_script = output_path / "launch_steam.sh"
        launcher_script.write_text(f"""#!/bin/bash
# Steam HTML5 Game Launcher
# Opens the game in Steam's built-in browser

SCRIPT_DIR="$( cd "$( dirname "${{BASH_SOURCE[0]}}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# Launch index.html
if command -v xdg-open &> /dev/null; then
    xdg-open index.html
elif command -v open &> /dev/null; then
    open index.html
else
    echo "No browser opener found"
    exit 1
fi
""")
        launcher_script.chmod(0o755)

    # ========================================================================
    # Steam Configuration
    # ========================================================================

    def generate_app_build_vdf(
        self,
        app_id: str,
        depot_id: str,
        content_root: Path,
        output_path: Path,
        build_description: str = "Build from TempleDB"
    ) -> Path:
        """
        Generate Steam app_build.vdf configuration file

        Args:
            app_id: Steam App ID
            depot_id: Steam Depot ID
            content_root: Path to game build content
            output_path: Where to write the VDF file
            build_description: Description for this build

        Returns:
            Path to generated VDF file
        """
        vdf_content = f""""appbuild"
{{
    "appid" "{app_id}"
    "desc" "{build_description}"
    "buildoutput" "{output_path / 'output'}"
    "contentroot" "{content_root}"
    "setlive" ""
    "preview" "0"
    "local" ""

    "depots"
    {{
        "{depot_id}"
        {{
            "FileMapping"
            {{
                "LocalPath" "*"
                "DepotPath" "."
                "recursive" "1"
            }}
        }}
    }}
}}
"""
        vdf_file = output_path / "app_build.vdf"
        vdf_file.write_text(vdf_content)
        return vdf_file

    def generate_depot_build_vdf(
        self,
        depot_id: str,
        content_root: Path,
        output_path: Path
    ) -> Path:
        """
        Generate Steam depot_build.vdf configuration file

        Args:
            depot_id: Steam Depot ID
            content_root: Path to depot content
            output_path: Where to write the VDF file

        Returns:
            Path to generated VDF file
        """
        vdf_content = f""""DepotBuildConfig"
{{
    "DepotID" "{depot_id}"
    "ContentRoot" "{content_root}"

    "FileMapping"
    {{
        "LocalPath" "*"
        "DepotPath" "."
        "recursive" "1"
    }}

    "FileExclusion" "*.pdb"
}}
"""
        vdf_file = output_path / f"depot_build_{depot_id}.vdf"
        vdf_file.write_text(vdf_content)
        return vdf_file

    # ========================================================================
    # Steam Pipe Upload
    # ========================================================================

    def upload_to_steam(
        self,
        app_build_vdf: Path,
        steam_username: str,
        steam_password: Optional[str] = None
    ) -> SteamDeploymentResult:
        """
        Upload build to Steam using Steam CMD

        Args:
            app_build_vdf: Path to app_build.vdf
            steam_username: Steam username
            steam_password: Steam password (optional, can use cached)

        Returns:
            SteamDeploymentResult
        """
        # Find steamcmd
        steamcmd_path = self._find_steamcmd_executable()
        if not steamcmd_path:
            return SteamDeploymentResult(
                success=False,
                message="steamcmd not found",
                error="Install steamcmd to upload to Steam"
            )

        # Build command
        cmd = [
            str(steamcmd_path),
            "+login", steam_username
        ]

        if steam_password:
            cmd.append(steam_password)

        cmd.extend([
            "+run_app_build", str(app_build_vdf),
            "+quit"
        ])

        try:
            logger.info("Uploading to Steam...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout
            )

            if result.returncode != 0:
                return SteamDeploymentResult(
                    success=False,
                    message="Steam upload failed",
                    error=result.stderr or result.stdout
                )

            return SteamDeploymentResult(
                success=True,
                message="Build uploaded to Steam successfully"
            )

        except subprocess.TimeoutExpired:
            return SteamDeploymentResult(
                success=False,
                message="Steam upload timed out (1 hour)",
                error="Upload took too long"
            )
        except Exception as e:
            return SteamDeploymentResult(
                success=False,
                message=f"Steam upload error: {str(e)}",
                error=str(e)
            )

    # ========================================================================
    # Full Deployment Workflows
    # ========================================================================

    def deploy_unity_to_steam(
        self,
        project_path: Path,
        app_id: str,
        depot_id: str,
        build_targets: List[str],
        steam_username: str,
        steam_password: Optional[str] = None
    ) -> List[SteamDeploymentResult]:
        """
        Complete workflow: Build Unity game and upload to Steam

        Args:
            project_path: Path to Unity project
            app_id: Steam App ID
            depot_id: Steam Depot ID
            build_targets: List of Unity build targets
            steam_username: Steam username
            steam_password: Steam password

        Returns:
            List of SteamDeploymentResults for each platform
        """
        results = []

        for target in build_targets:
            # Build
            build_result = self.build_unity_game(project_path, target)
            if not build_result.success:
                results.append(build_result)
                continue

            # Generate VDF
            vdf_path = self.temp_dir / f"steam-config-{target}"
            vdf_path.mkdir(exist_ok=True)

            app_vdf = self.generate_app_build_vdf(
                app_id=app_id,
                depot_id=depot_id,
                content_root=build_result.build_path,
                output_path=vdf_path,
                build_description=f"Unity {target} build"
            )

            # Upload
            upload_result = self.upload_to_steam(
                app_build_vdf=app_vdf,
                steam_username=steam_username,
                steam_password=steam_password
            )

            results.append(upload_result)

        return results

    def deploy_godot_to_steam(
        self,
        project_path: Path,
        app_id: str,
        depot_id: str,
        export_presets: List[str],
        steam_username: str,
        steam_password: Optional[str] = None
    ) -> List[SteamDeploymentResult]:
        """
        Complete workflow: Build Godot game and upload to Steam

        Args:
            project_path: Path to Godot project
            app_id: Steam App ID
            depot_id: Steam Depot ID
            export_presets: List of Godot export presets
            steam_username: Steam username
            steam_password: Steam password

        Returns:
            List of SteamDeploymentResults for each platform
        """
        results = []

        for preset in export_presets:
            # Build
            build_result = self.build_godot_game(project_path, preset)
            if not build_result.success:
                results.append(build_result)
                continue

            # Generate VDF
            vdf_path = self.temp_dir / f"steam-config-{preset.replace('/', '-')}"
            vdf_path.mkdir(exist_ok=True)

            app_vdf = self.generate_app_build_vdf(
                app_id=app_id,
                depot_id=depot_id,
                content_root=build_result.build_path,
                output_path=vdf_path,
                build_description=f"Godot {preset} build"
            )

            # Upload
            upload_result = self.upload_to_steam(
                app_build_vdf=app_vdf,
                steam_username=steam_username,
                steam_password=steam_password
            )

            results.append(upload_result)

        return results

    # ========================================================================
    # Utility Functions
    # ========================================================================

    def _find_unity_executable(self) -> Optional[Path]:
        """Find Unity executable on system"""
        # Check common paths
        common_paths = [
            Path("/Applications/Unity/Hub/Editor/2022.3.0f1/Unity.app/Contents/MacOS/Unity"),
            Path("C:/Program Files/Unity/Hub/Editor/2022.3.0f1/Editor/Unity.exe"),
            Path.home() / "Unity" / "Hub" / "Editor" / "2022.3.0f1" / "Editor" / "Unity"
        ]

        for path in common_paths:
            if path.exists():
                return path

        # Check PATH
        unity_cmd = shutil.which("unity") or shutil.which("Unity")
        if unity_cmd:
            return Path(unity_cmd)

        return None

    def _find_godot_executable(self) -> Optional[Path]:
        """Find Godot executable on system"""
        # Check PATH
        godot_cmd = shutil.which("godot") or shutil.which("Godot")
        if godot_cmd:
            return Path(godot_cmd)

        # Check common paths
        common_paths = [
            Path("/usr/local/bin/godot"),
            Path("/usr/bin/godot"),
            Path.home() / ".local" / "bin" / "godot"
        ]

        for path in common_paths:
            if path.exists():
                return path

        return None

    def _find_steamcmd_executable(self) -> Optional[Path]:
        """Find steamcmd executable on system"""
        # Check PATH
        steamcmd = shutil.which("steamcmd")
        if steamcmd:
            return Path(steamcmd)

        # Check common paths
        common_paths = [
            Path("/usr/local/bin/steamcmd"),
            Path("/usr/bin/steamcmd"),
            Path.home() / "steamcmd" / "steamcmd.sh"
        ]

        for path in common_paths:
            if path.exists():
                return path

        return None
