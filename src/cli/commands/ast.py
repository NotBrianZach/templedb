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
    else:
        print("Usage: templedb ast {build|diff|list|show}", file=sys.stderr)
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
