"""CLI commands for AST-based deploy builds.

templedb ast {build, diff, list, show}
Design: docs/AST_DEPLOY_DESIGN.md
"""

import json
import sys

from services.ast_build_service import AstBuildService


def register(cli):
    parser = cli.register_command(
        'ast', handle, help_text='AST-based NixOS config builds')
    sub = parser.add_subparsers(dest='ast_command')

    p = sub.add_parser('build', help='Emit AST → .nix, hash, write content-addressed build dir')
    p.add_argument('--host', required=True, help='Host name (see `templedb config-ast host list`)')
    p.add_argument('--scope', action='append', choices=['system', 'home', 'flake'],
                   help='Scope to emit (repeatable; default all three)')
    p.add_argument('--nix-build', action='store_true',
                   help='Run `nix build` against the flake in the build dir to verify buildability')
    p.add_argument('--copy-support-files', action='store_true',
                   help='Copy non-AST files from the live checkout into the build dir '
                        '(implied by --nix-build)')
    p.add_argument('--json', action='store_true', help='Emit machine-readable result')

    p = sub.add_parser('diff', help='Diff two builds, or a build against the live checkout')
    p.add_argument('ref_a', help='Hash prefix (>=8 chars) or "live"')
    p.add_argument('ref_b', nargs='?', default='live',
                   help='Hash prefix or "live" (default: live)')
    p.add_argument('--host', help='Disambiguate when a hash prefix matches multiple hosts')

    p = sub.add_parser('list', help='List past builds')
    p.add_argument('--host', help='Filter by host')

    p = sub.add_parser('show', help='Show manifest and file list for a build')
    p.add_argument('hash_prefix', help='Hash prefix (>=8 chars)')
    p.add_argument('--host', help='Disambiguate when a hash prefix matches multiple hosts')

    p = sub.add_parser('promote', help='Write an AST build\'s files into the live system_config checkout')
    p.add_argument('hash_prefix', help='Hash prefix (>=8 chars)')
    p.add_argument('--host', help='Disambiguate when a hash prefix matches multiple hosts')
    p.add_argument('--yes', action='store_true',
                   help='Skip the "N files will change" confirmation prompt')
    p.add_argument('--force-unbuildable', action='store_true',
                   help='Promote even if the build was never verified with `--nix-build`')

    p = sub.add_parser('deploy', help='Promote a build and run `nixos-rebuild switch` locally')
    p.add_argument('hash_prefix', help='Hash prefix (>=8 chars)')
    p.add_argument('--host', help='Disambiguate when a hash prefix matches multiple hosts')
    p.add_argument('--mode', default='switch', choices=['switch', 'test', 'boot', 'dry-activate'],
                   help='nixos-rebuild mode (default: switch)')
    p.add_argument('--yes', action='store_true',
                   help='Skip the confirmation prompt')
    p.add_argument('--force-unbuildable', action='store_true',
                   help='Deploy even if the build was never verified with `--nix-build`')


def handle(args):
    cmd = args.ast_command
    svc = AstBuildService()

    if cmd == 'build':
        return _handle_build(svc, args)
    elif cmd == 'diff':
        return _handle_diff(svc, args)
    elif cmd == 'list':
        return _handle_list(svc, args)
    elif cmd == 'show':
        return _handle_show(svc, args)
    elif cmd == 'promote':
        return _handle_promote(svc, args)
    elif cmd == 'deploy':
        return _handle_deploy(svc, args)
    else:
        print("Usage: templedb ast {build|diff|list|show|promote|deploy}", file=sys.stderr)
        return 1


def _handle_build(svc, args):
    try:
        result = svc.build(
            host_name=args.host,
            scopes=args.scope,
            run_nix_build=args.nix_build,
            copy_support_files=args.copy_support_files or args.nix_build,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0

    print(f"hash:        {result['output_hash']}")
    print(f"host:        {result['host_name']}")
    print(f"scopes:      {', '.join(result['scopes']) if isinstance(result['scopes'], list) else result['scopes']}")
    print(f"path:        {result['output_path']}")
    if result.get('nix_buildable') == 1:
        print(f"nix build:   OK")
    elif result.get('nix_buildable') == 0:
        print(f"nix build:   FAILED")
        err = result.get('nix_build_error') or ''
        for line in err.splitlines()[-20:]:
            print(f"  | {line}")
    else:
        print(f"nix build:   skipped (pass --nix-build to verify)")
    return 0 if result.get('nix_buildable') != 0 else 2


def _handle_diff(svc, args):
    try:
        d = svc.diff(args.ref_a, args.ref_b, host_name=args.host)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not d:
        print("(no differences)")
        return 0
    print(d)
    return 0


def _handle_list(svc, args):
    rows = svc.list_builds(args.host)
    if not rows:
        print("(no builds)")
        return 0
    print(f"{'HASH':<14} {'HOST':<28} {'BUILT':<20} {'NIX':<8} SCOPES")
    for r in rows:
        buildable = {1: 'ok', 0: 'FAIL'}.get(r.get('nix_buildable'), '-')
        scopes = ','.join(r['scopes']) if isinstance(r['scopes'], list) else r['scopes']
        print(f"{r['output_hash'][:12]:<14} {r['host_name']:<28} "
              f"{str(r['generated_at'])[:19]:<20} {buildable:<8} {scopes}")
    return 0


def _handle_show(svc, args):
    row = svc.get_build(args.hash_prefix, host_name=args.host)
    if not row:
        print(f"no build matching {args.hash_prefix!r}", file=sys.stderr)
        return 1
    print(json.dumps(row, indent=2, default=str))
    return 0


def _handle_promote(svc, args):
    row = svc.get_build(args.hash_prefix, host_name=args.host)
    if not row:
        print(f"no build matching {args.hash_prefix!r}", file=sys.stderr)
        return 1

    # Show what's already promoted for this host and what would change
    current = svc.current_promoted(row['host_name'])
    if current and current['output_hash'] == row['output_hash']:
        print(f"build {row['output_hash'][:12]} is already the promoted build for "
              f"{row['host_name']} (promoted {current['promoted_at']})")
        return 0
    if current:
        print(f"currently promoted for {row['host_name']}: "
              f"{current['output_hash'][:12]} ({current['promoted_at']})")

    try:
        diff = svc.diff(args.hash_prefix, 'live', host_name=args.host)
    except ValueError as e:
        diff = f"(could not compute diff: {e})"
    changed_files = sum(1 for line in diff.splitlines() if line.startswith('--- '))
    print(f"promoting {row['output_hash'][:12]} for {row['host_name']} "
          f"— {changed_files} file(s) will change")

    if not args.yes:
        print("re-run with --yes to actually write. (Use `templedb ast diff "
              f"{row['output_hash'][:12]} live --host {row['host_name']}` to see diff.)")
        return 0

    try:
        result = svc.promote(
            args.hash_prefix, host_name=args.host,
            require_buildable=not args.force_unbuildable,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"promoted. wrote {len(result['_written_files'])} file(s):")
    for f in result['_written_files']:
        print(f"  {f}")
    print(f"next: run `sudo nixos-rebuild switch --flake ~/.config/templedb/checkouts/system_config#{row['host_name']}`")
    return 0


def _handle_deploy(svc, args):
    """Promote an AST build then invoke SystemService.switch_system locally.

    Order: verify buildable → confirm with user → promote → switch_system.
    Refuses if the target host doesn't match the current machine's hostname
    (deploying host A's config on machine B would activate the wrong system).
    """
    import socket
    row = svc.get_build(args.hash_prefix, host_name=args.host)
    if not row:
        print(f"no build matching {args.hash_prefix!r}", file=sys.stderr)
        return 1

    local_host = socket.gethostname()
    if row['host_name'] != local_host:
        print(f"error: build is for host {row['host_name']!r} but this machine "
              f"is {local_host!r}. Refusing to activate the wrong host's config. "
              f"Use `templedb ast promote` alone on the correct machine, or "
              f"deploy via fleet from a controller.", file=sys.stderr)
        return 1

    if not args.force_unbuildable and row.get('nix_buildable') != 1:
        print(f"error: build {row['output_hash'][:12]} not verified. Run "
              f"`templedb ast build --host {row['host_name']} --nix-build` first, "
              f"or pass --force-unbuildable.", file=sys.stderr)
        return 1

    print(f"deploying {row['output_hash'][:12]} to {local_host} "
          f"(mode: {args.mode})")
    if not args.yes:
        print(f"re-run with --yes to promote and run `nixos-rebuild {args.mode}`.")
        return 0

    # Promote first
    try:
        result = svc.promote(
            args.hash_prefix, host_name=args.host,
            require_buildable=not args.force_unbuildable,
        )
        print(f"promoted. wrote {len(result['_written_files'])} file(s).")
    except ValueError as e:
        print(f"promote error: {e}", file=sys.stderr)
        return 1

    # Then rebuild locally via SystemService
    from services.system_service import SystemService, SystemServiceError
    from pathlib import Path
    sysvc = SystemService()
    checkout_path = Path.home() / ".config" / "templedb" / "checkouts" / "system_config"

    try:
        if args.mode == 'switch':
            rebuild = sysvc.switch_system(
                project_slug='system_config',
                checkout_path=checkout_path,
            )
        elif args.mode == 'test':
            rebuild = sysvc.test_system(
                project_slug='system_config',
                checkout_path=checkout_path,
            )
        elif args.mode == 'boot':
            rebuild = sysvc._run_nixos_rebuild(
                'boot', checkout_path=checkout_path)
        elif args.mode == 'dry-activate':
            rebuild = sysvc._run_nixos_rebuild(
                'dry-activate', checkout_path=checkout_path)
    except SystemServiceError as e:
        print(f"rebuild error: {e}", file=sys.stderr)
        return 2

    if isinstance(rebuild, dict) and rebuild.get('success'):
        print(f"✓ nixos-rebuild {args.mode} succeeded")
        return 0
    print(f"nixos-rebuild {args.mode} returned: {rebuild}", file=sys.stderr)
    return 2
