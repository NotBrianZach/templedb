#!/usr/bin/env python3
"""
Cathedral Package Format - Portable TempleDB project packages

A .cathedral package is a directory structure containing:
  manifest.json          - Package metadata and checksums
  project.json           - Project metadata
  files/                 - File metadata and content
  vcs/                   - Version control data (branches, commits, history)
  environments/          - Nix environments
  deployments/           - Deployment configurations
  dependencies/          - Dependency graph
  secrets/               - Encrypted secrets (optional)
  metadata/              - Additional metadata (stats, tags, readme)
"""

import os
import json
import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

CATHEDRAL_FORMAT_VERSION = "1.0.0"
CATHEDRAL_SCHEMA_VERSION = 7  # Current TempleDB schema version


@dataclass
class CathedralManifest:
    """Manifest for a .cathedral package"""
    version: str  # Format version
    format: str   # Always "cathedral-package"
    created_at: str
    created_by: str
    project: Dict[str, Any]  # Project info (slug, name, description, etc)
    source: Dict[str, Any]   # Source info (templedb version, schema, etc)
    contents: Dict[str, Any] # Contents summary (files, commits, size, etc)
    checksums: Dict[str, str] # SHA256 checksums
    signature: Optional[Dict[str, str]] = None  # Optional age/gpg signature

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'CathedralManifest':
        return cls(**data)


@dataclass
class ProjectMetadata:
    """Project metadata for export"""
    slug: str
    name: str
    description: Optional[str]
    repository_url: Optional[str]
    default_branch: Optional[str]
    git_ref: Optional[str]
    created_at: str
    updated_at: str
    metadata: Dict[str, Any]
    statistics: Dict[str, Any]

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'ProjectMetadata':
        return cls(**data)


@dataclass
class FileMetadata:
    """File metadata for export"""
    file_id: int
    file_path: str
    file_type: Optional[str]
    lines_of_code: int
    file_size_bytes: int
    hash_sha256: str
    version_number: int
    author: Optional[str]
    created_at: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'FileMetadata':
        return cls(**data)


class CathedralPackage:
    """Represents a .cathedral package on disk"""

    def __init__(self, package_path: Path):
        self.package_path = Path(package_path)
        self.manifest_path = self.package_path / "manifest.json"
        self.project_path = self.package_path / "project.json"
        self.files_dir = self.package_path / "files"
        self.vcs_dir = self.package_path / "vcs"
        self.environments_dir = self.package_path / "environments"
        self.deployments_dir = self.package_path / "deployments"
        self.dependencies_dir = self.package_path / "dependencies"
        self.secrets_dir = self.package_path / "secrets"
        self.metadata_dir = self.package_path / "metadata"

    def create_structure(self):
        """Create package directory structure"""
        self.package_path.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(exist_ok=True)
        self.vcs_dir.mkdir(exist_ok=True)
        self.environments_dir.mkdir(exist_ok=True)
        self.deployments_dir.mkdir(exist_ok=True)
        self.dependencies_dir.mkdir(exist_ok=True)
        self.secrets_dir.mkdir(exist_ok=True)
        self.metadata_dir.mkdir(exist_ok=True)

    def write_manifest(self, manifest: CathedralManifest):
        """Write manifest.json"""
        with open(self.manifest_path, 'w') as f:
            json.dump(manifest.to_dict(), f, indent=2)

    def read_manifest(self) -> CathedralManifest:
        """Read manifest.json"""
        with open(self.manifest_path, 'r') as f:
            data = json.load(f)
        return CathedralManifest.from_dict(data)

    def write_project(self, project: ProjectMetadata):
        """Write project.json"""
        with open(self.project_path, 'w') as f:
            json.dump(project.to_dict(), f, indent=2)

    def read_project(self) -> ProjectMetadata:
        """Read project.json"""
        with open(self.project_path, 'r') as f:
            data = json.load(f)
        return ProjectMetadata.from_dict(data)

    def write_file_metadata(self, file_id: int, metadata: FileMetadata):
        """Write file metadata as JSON"""
        file_json = self.files_dir / f"file-{file_id:06d}.json"
        with open(file_json, 'w') as f:
            json.dump(metadata.to_dict(), f, indent=2)

    def write_file_content(self, file_id: int, content: bytes):
        """Write file content as blob"""
        file_blob = self.files_dir / f"file-{file_id:06d}.blob"
        with open(file_blob, 'wb') as f:
            f.write(content)

    def read_file_metadata(self, file_id: int) -> FileMetadata:
        """Read file metadata"""
        file_json = self.files_dir / f"file-{file_id:06d}.json"
        with open(file_json, 'r') as f:
            data = json.load(f)
        return FileMetadata.from_dict(data)

    def read_file_content(self, file_id: int) -> bytes:
        """Read file content"""
        file_blob = self.files_dir / f"file-{file_id:06d}.blob"
        with open(file_blob, 'rb') as f:
            return f.read()

    def write_vcs_data(self, branches: List[Dict], commits: List[Dict], history: List[Dict]):
        """Write VCS data"""
        with open(self.vcs_dir / "branches.json", 'w') as f:
            json.dump(branches, f, indent=2)
        with open(self.vcs_dir / "commits.json", 'w') as f:
            json.dump(commits, f, indent=2)
        with open(self.vcs_dir / "history.json", 'w') as f:
            json.dump(history, f, indent=2)

    def read_vcs_data(self) -> tuple[List[Dict], List[Dict], List[Dict]]:
        """Read VCS data"""
        with open(self.vcs_dir / "branches.json", 'r') as f:
            branches = json.load(f)
        with open(self.vcs_dir / "commits.json", 'r') as f:
            commits = json.load(f)
        with open(self.vcs_dir / "history.json", 'r') as f:
            history = json.load(f)
        return branches, commits, history

    def write_files_manifest(self, files: List[FileMetadata]):
        """Write files/manifest.json with list of all files"""
        manifest = {
            "total_files": len(files),
            "files": [{"file_id": f.file_id, "file_path": f.file_path, "hash_sha256": f.hash_sha256} for f in files]
        }
        with open(self.files_dir / "manifest.json", 'w') as f:
            json.dump(manifest, f, indent=2)

    def calculate_package_checksum(self) -> str:
        """Calculate SHA256 checksum of entire package"""
        hasher = hashlib.sha256()

        # Hash all files in deterministic order
        for root, dirs, files in os.walk(str(self.package_path)):
            dirs.sort()
            for file in sorted(files):
                if file == "manifest.json":  # Skip manifest (it contains the checksum)
                    continue
                filepath = Path(root) / file
                with open(filepath, 'rb') as f:
                    hasher.update(f.read())

        return hasher.hexdigest()

    def verify_integrity(self) -> bool:
        """Verify package integrity using checksums"""
        manifest = self.read_manifest()
        expected = manifest.checksums.get('sha256')
        if not expected:
            return False

        actual = self.calculate_package_checksum()
        return actual == expected


def create_manifest(
    project_slug: str,
    project_name: str,
    creator: str,
    total_files: int,
    total_commits: int,
    total_branches: int,
    total_size_bytes: int,
    has_secrets: bool,
    has_environments: bool,
    templedb_version: str = "0.1.0",
    schema_version: int = CATHEDRAL_SCHEMA_VERSION
) -> CathedralManifest:
    """Create a cathedral manifest"""

    return CathedralManifest(
        version=CATHEDRAL_FORMAT_VERSION,
        format="cathedral-package",
        created_at=datetime.utcnow().isoformat() + "Z",
        created_by=creator,
        project={
            "slug": project_slug,
            "name": project_name,
            "visibility": "private",  # Default, can be overridden
            "license": None
        },
        source={
            "templedb_version": templedb_version,
            "schema_version": schema_version,
            "export_method": "full"
        },
        contents={
            "files": total_files,
            "commits": total_commits,
            "branches": total_branches,
            "total_size_bytes": total_size_bytes,
            "has_secrets": has_secrets,
            "has_environments": has_environments
        },
        checksums={
            "sha256": "",  # Will be filled in after package creation
            "algorithm": "sha256"
        },
        signature=None  # Optional
    )
