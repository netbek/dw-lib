#!/bin/bash

command_exists() {
    command -v "$1" > /dev/null 2>&1
}

version_gte() {
    local cmd="$1"
    local required_version="$2"
    local installed_version=$($cmd | grep -oE "[0-9]+(\.[0-9]+)+" | head -n 1)

    if [ -z "$installed_version" ]; then
        return 1
    fi

    IFS="."
    set -- $installed_version
    local installed_parts="$@"
    set -- $required_version
    local required_parts="$@"
    unset IFS

    local i=1
    for required_part in $required_parts; do
        installed_part=$(echo "$installed_parts" | cut -d " " -f $i)
        if [ "${installed_part:-0}" -lt "$required_part" ]; then
            return 1
        elif [ "${installed_part:-0}" -gt "$required_part" ]; then
            return 0
        fi
        i=$((i + 1))
    done

    return 0
}
