#!/usr/bin/env bash
# Bash completion for templedb CLI
# Install: source this file or copy to /etc/bash_completion.d/

_templedb_completion() {
    local cur prev words cword
    _init_completion || return

    local commands="help status tui project env vcs search llm backup restore"
    local project_cmds="import list sync"
    local env_cmds="enter list detect new generate"
    local vcs_cmds="commit status log branch"
    local search_cmds="content files"
    local llm_cmds="context export schema"

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
                project)
                    COMPREPLY=( $(compgen -W "${project_cmds}" -- "${cur}") )
                    ;;
                env)
                    COMPREPLY=( $(compgen -W "${env_cmds}" -- "${cur}") )
                    ;;
                vcs)
                    COMPREPLY=( $(compgen -W "${vcs_cmds}" -- "${cur}") )
                    ;;
                search)
                    COMPREPLY=( $(compgen -W "${search_cmds}" -- "${cur}") )
                    ;;
                llm)
                    COMPREPLY=( $(compgen -W "${llm_cmds}" -- "${cur}") )
                    ;;
                backup|restore)
                    # File completion
                    _filedir
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
                        enter|list|detect|new|generate)
                            # Complete project slugs
                            if command -v templedb &> /dev/null; then
                                local projects=$(templedb project list 2>/dev/null | awk 'NR>3 && NF {print $1}')
                                COMPREPLY=( $(compgen -W "${projects}" -- "${cur}") )
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
                        status|log|branch)
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
                        content|files)
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
                llm)
                    case "${subcmd}" in
                        context|export)
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
                backup|restore)
                    # File completion
                    _filedir
                    ;;
            esac
            ;;
    esac

    return 0
}

# Register completion
complete -F _templedb_completion templedb
