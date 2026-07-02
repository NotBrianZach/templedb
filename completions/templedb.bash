#!/usr/bin/env bash
# Bash completion for templedb CLI
# Install: source this file or copy to /etc/bash_completion.d/

_templedb_completion() {
    local cur prev words cword
    _init_completion || return

    local commands="help status env deploy ai storage admin sync search graph publish project vcs file nixos config tutorial domain merge gui dev"

    # Subcommands for each top-level command
    local env_cmds="enter list detect new generate secret var key direnv"
    local deploy_cmds="run status history rollback targets migration trigger notify nix nixops4 hooks"
    local ai_cmds="claude vibe prompt mcp context export schema"
    local storage_cmds="backup restore cathedral blob"
    local admin_cmds="db cache schema gitserver"
    local sync_cmds="init status serve push pull sync peers network"
    local search_cmds="query query-open content files"
    local graph_cmds="search who-uses build-deps importers callers"
    local publish_cmds="run"
    local project_cmds="import list sync"
    local vcs_cmds="commit status log branch add diff switch merge"
    local file_cmds="list show edit"
    local nixos_cmds="build switch rebuild"
    local config_cmds="get set list edit"
    local tutorial_cmds="list start"
    local domain_cmds="list add remove"
    local merge_cmds="start finish abort"
    local gui_cmds="start"
    local dev_cmds="repl test lint"

    # Get current command context
    local cmd="${words[1]}"
    local subcmd="${words[2]}"

    case "${cword}" in
        1)
            # First argument: top-level commands
            COMPREPLY=( $(compgen -W "${commands}" -- "${cur}") )
            ;;
        2)
            # Second argument: subcommands
            case "${cmd}" in
                env)
                    COMPREPLY=( $(compgen -W "${env_cmds}" -- "${cur}") )
                    ;;
                deploy)
                    COMPREPLY=( $(compgen -W "${deploy_cmds}" -- "${cur}") )
                    ;;
                ai)
                    COMPREPLY=( $(compgen -W "${ai_cmds}" -- "${cur}") )
                    ;;
                storage)
                    COMPREPLY=( $(compgen -W "${storage_cmds}" -- "${cur}") )
                    ;;
                admin)
                    COMPREPLY=( $(compgen -W "${admin_cmds}" -- "${cur}") )
                    ;;
                sync)
                    COMPREPLY=( $(compgen -W "${sync_cmds}" -- "${cur}") )
                    ;;
                search)
                    COMPREPLY=( $(compgen -W "${search_cmds}" -- "${cur}") )
                    ;;
                graph)
                    COMPREPLY=( $(compgen -W "${graph_cmds}" -- "${cur}") )
                    ;;
                publish)
                    COMPREPLY=( $(compgen -W "${publish_cmds}" -- "${cur}") )
                    ;;
                project)
                    COMPREPLY=( $(compgen -W "${project_cmds}" -- "${cur}") )
                    ;;
                vcs)
                    COMPREPLY=( $(compgen -W "${vcs_cmds}" -- "${cur}") )
                    ;;
                file)
                    COMPREPLY=( $(compgen -W "${file_cmds}" -- "${cur}") )
                    ;;
                nixos)
                    COMPREPLY=( $(compgen -W "${nixos_cmds}" -- "${cur}") )
                    ;;
                config)
                    COMPREPLY=( $(compgen -W "${config_cmds}" -- "${cur}") )
                    ;;
                tutorial)
                    COMPREPLY=( $(compgen -W "${tutorial_cmds}" -- "${cur}") )
                    ;;
                domain)
                    COMPREPLY=( $(compgen -W "${domain_cmds}" -- "${cur}") )
                    ;;
                merge)
                    COMPREPLY=( $(compgen -W "${merge_cmds}" -- "${cur}") )
                    ;;
                gui)
                    COMPREPLY=( $(compgen -W "${gui_cmds}" -- "${cur}") )
                    ;;
                dev)
                    COMPREPLY=( $(compgen -W "${dev_cmds}" -- "${cur}") )
                    ;;
            esac
            ;;
        *)
            # Additional arguments: project names, flags, paths
            case "${cmd}" in
                project)
                    case "${subcmd}" in
                        import|sync)
                            # Directory completion
                            _filedir -d
                            ;;
                        *)
                            # Project slug completion
                            if command -v templedb &> /dev/null; then
                                local projects=$(templedb project list 2>/dev/null | awk 'NR>3 && NF {print $1}')
                                COMPREPLY=( $(compgen -W "${projects}" -- "${cur}") )
                            fi
                            ;;
                    esac
                    ;;
                env)
                    case "${subcmd}" in
                        enter|list|detect|new|generate|secret|var|key|direnv)
                            # Complete project slugs
                            if command -v templedb &> /dev/null; then
                                local projects=$(templedb project list 2>/dev/null | awk 'NR>3 && NF {print $1}')
                                COMPREPLY=( $(compgen -W "${projects}" -- "${cur}") )
                            fi
                            ;;
                    esac
                    ;;
                deploy)
                    case "${subcmd}" in
                        target|migration|trigger|notify)
                            if [[ "${cur}" == -* ]]; then
                                COMPREPLY=( $(compgen -W "-p --project" -- "${cur}") )
                            elif [[ "${prev}" == "-p" || "${prev}" == "--project" ]]; then
                                if command -v templedb &> /dev/null; then
                                    local projects=$(templedb project list 2>/dev/null | awk 'NR>3 && NF {print $1}')
                                    COMPREPLY=( $(compgen -W "${projects}" -- "${cur}") )
                                fi
                            fi
                            ;;
                    esac
                    ;;
                ai)
                    case "${subcmd}" in
                        claude|vibe|prompt|mcp|context|export)
                            # Flags and project completion
                            if [[ "${cur}" == -* ]]; then
                                COMPREPLY=( $(compgen -W "-p -o --project --output" -- "${cur}") )
                            elif [[ "${prev}" == "-p" || "${prev}" == "--project" ]]; then
                                if command -v templedb &> /dev/null; then
                                    local projects=$(templedb project list 2>/dev/null | awk 'NR>3 && NF {print $1}')
                                    COMPREPLY=( $(compgen -W "${projects}" -- "${cur}") )
                                fi
                            elif [[ "${prev}" == "-o" || "${prev}" == "--output" ]]; then
                                _filedir
                            fi
                            ;;
                    esac
                    ;;
                storage)
                    case "${subcmd}" in
                        backup|restore|cathedral|blob)
                            # File completion
                            _filedir
                            ;;
                    esac
                    ;;
                admin)
                    case "${subcmd}" in
                        db|cache|schema|gitserver)
                            if [[ "${cur}" == -* ]]; then
                                COMPREPLY=( $(compgen -W "-p --project" -- "${cur}") )
                            elif [[ "${prev}" == "-p" || "${prev}" == "--project" ]]; then
                                if command -v templedb &> /dev/null; then
                                    local projects=$(templedb project list 2>/dev/null | awk 'NR>3 && NF {print $1}')
                                    COMPREPLY=( $(compgen -W "${projects}" -- "${cur}") )
                                fi
                            fi
                            ;;
                    esac
                    ;;
                vcs)
                    case "${subcmd}" in
                        commit)
                            # Flags and project completion
                            if [[ "${cur}" == -* ]]; then
                                COMPREPLY=( $(compgen -W "-m -p -b -a --message --project --branch --author" -- "${cur}") )
                            elif [[ "${prev}" == "-p" || "${prev}" == "--project" ]]; then
                                if command -v templedb &> /dev/null; then
                                    local projects=$(templedb project list 2>/dev/null | awk 'NR>3 && NF {print $1}')
                                    COMPREPLY=( $(compgen -W "${projects}" -- "${cur}") )
                                fi
                            fi
                            ;;
                        status|log|branch|add|diff|switch|merge)
                            # Project slug completion
                            if [[ "${cur}" == -* ]]; then
                                COMPREPLY=( $(compgen -W "-n" -- "${cur}") )
                            else
                                if command -v templedb &> /dev/null; then
                                    local projects=$(templedb project list 2>/dev/null | awk 'NR>3 && NF {print $1}')
                                    COMPREPLY=( $(compgen -W "${projects}" -- "${cur}") )
                                fi
                            fi
                            ;;
                    esac
                    ;;
                search)
                    case "${subcmd}" in
                        query|query-open|content|files)
                            # Flags completion
                            if [[ "${cur}" == -* ]]; then
                                COMPREPLY=( $(compgen -W "-p -i --project --ignore-case" -- "${cur}") )
                            elif [[ "${prev}" == "-p" || "${prev}" == "--project" ]]; then
                                if command -v templedb &> /dev/null; then
                                    local projects=$(templedb project list 2>/dev/null | awk 'NR>3 && NF {print $1}')
                                    COMPREPLY=( $(compgen -W "${projects}" -- "${cur}") )
                                fi
                            fi
                            ;;
                    esac
                    ;;
                graph)
                    case "${subcmd}" in
                        search|who-uses|build-deps|importers|callers)
                            if command -v templedb &> /dev/null; then
                                local projects=$(templedb project list 2>/dev/null | awk 'NR>3 && NF {print $1}')
                                COMPREPLY=( $(compgen -W "${projects}" -- "${cur}") )
                            fi
                            ;;
                    esac
                    ;;
                publish)
                    case "${subcmd}" in
                        run)
                            if [[ "${cur}" == -* ]]; then
                                COMPREPLY=( $(compgen -W "-m --message" -- "${cur}") )
                            else
                                if command -v templedb &> /dev/null; then
                                    local projects=$(templedb project list 2>/dev/null | awk 'NR>3 && NF {print $1}')
                                    COMPREPLY=( $(compgen -W "${projects}" -- "${cur}") )
                                fi
                            fi
                            ;;
                    esac
                    ;;
                sync)
                    case "${subcmd}" in
                        network|push|pull)
                            if command -v templedb &> /dev/null; then
                                local projects=$(templedb project list 2>/dev/null | awk 'NR>3 && NF {print $1}')
                                COMPREPLY=( $(compgen -W "${projects}" -- "${cur}") )
                            fi
                            ;;
                    esac
                    ;;
            esac
            ;;
    esac

    return 0
}

# Register completion
complete -F _templedb_completion templedb
