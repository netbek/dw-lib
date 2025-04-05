#/bin/bash

scripts_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root_dir="${scripts_dir}/.."

build() {
    docker compose build
}

clean() {
    sudo chown -R $(id -u):$(id -g) .

    local dirs=(
        .cache
        .ipynb_checkpoints
        .local
        .pytest_cache
        .ruff_cache
        .ssh
        __pycache__
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

destroy() {
    docker compose down -v --remove-orphans --rmi local
    docker builder prune -f
}

up() {
    docker compose up -d
}

down() {
    docker compose down
}

shell() {
    docker compose up -d
    docker compose exec app bash
}

vscode() {
    docker compose up -d
    p=$(printf "%s" "$PWD" | xxd -p) && code --remote "dev-container+${p//[[:space:]]/}" "/app"
}

test() {
    docker compose up -d
    docker compose exec app /wait-for-it.sh postgres:5432 -- /wait-for-it.sh clickhouse:8123 -- /wait-for-it.sh peerdb-ui:3000 -- pytest
    docker compose down
}

cd "${root_dir}"
$1
