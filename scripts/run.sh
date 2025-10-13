#/bin/bash

scripts_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root_dir="${scripts_dir}/.."

clean() {
    sudo chown -R $(id -u):$(id -g) .

    local dirs=(
        __pycache__
        .cache
        .ipynb_checkpoints
        .local
        .pytest_cache
        .ruff_cache
        .ssh
    )

    local files=(
        .bash_history
        .bash_logout
        .python_history
    )

    for dir in "${dirs[@]}"; do
        find . -type d -name "$dir" -exec rm -r {} +
    done

    for file in "${files[@]}"; do
        find . -type f -name "$file" -exec rm {} +
    done
}

test() {
    uv run --frozen pytest
}

cd "${root_dir}"
$1
