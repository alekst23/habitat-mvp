#!/bin/sh
# The CI command remains the reviewed verification adapter. Only its environment changes.
set -eu
if [ "$#" -ne 0 ]; then
    echo "The verification environment accepts no alternate command or scope." >&2
    exit 2
fi
root=$(pwd)
: "${CI_COMMIT_SHA:?Actual CI commit identity is required}"
: "${CI_JOB_ID:?Actual CI job identity is required}"
[ "$(git rev-parse HEAD)" = "$CI_COMMIT_SHA" ]
[ -z "$(git status --porcelain --untracked-files=normal)" ]
case "$CI_JOB_ID" in ''|*[!0-9]*) exit 2;; esac
mkdir -p .ctx
scratch=$(mktemp -d "$root/.ctx/verify-environment.XXXXXX")
container=""
cleanup() {
    if [ -n "$container" ]; then docker rm --force "$container" >/dev/null 2>&1 || true; fi
    rm -rf "$scratch"
}
trap cleanup EXIT HUP INT TERM
mkdir -p "$scratch/build/backend"
cp .gitlab/ctx/Dockerfile.verify "$scratch/build/Dockerfile"
cp backend/requirements.lock "$scratch/build/backend/"
cp requirements-workflow.txt requirements-browser.txt requirements-render.txt "$scratch/build/"
image="habitat-verify:$CI_JOB_ID"
docker build --tag "$image" "$scratch/build"
# A local clone retains exact committed history without copying checkout caches or
# the runner's authenticated remote URL. No CI token or provider key enters tests.
git clone --quiet --no-hardlinks --no-checkout "$root" "$scratch/source"
git -C "$scratch/source" checkout --quiet --detach "$CI_COMMIT_SHA"
container=$(docker create --init --network none --user pwuser \
    --security-opt "seccomp=$root/browser-service/seccomp_profile.json" \
    --env BROWSER_REAL_TEST=1 --env HOME=/home/pwuser \
    --env CI_PROJECT_ID --env CI_COMMIT_SHA --env CI_COMMIT_BRANCH --env CI_DEFAULT_BRANCH \
    --env CI_MERGE_REQUEST_SOURCE_BRANCH_NAME --env CI_MERGE_REQUEST_TARGET_BRANCH_NAME \
    --env CI_MERGE_REQUEST_DIFF_BASE_SHA --env CI_COMMIT_BEFORE_SHA \
    --env CI_PIPELINE_ID --env CI_JOB_ID --env CI_JOB_URL \
    "$image" sleep infinity)
docker cp "$scratch/source/." "$container:/workspace/"
docker start "$container" >/dev/null
# Only copied fixture files change ownership; tests and Chromium run as pwuser.
docker exec --user root "$container" chown -R pwuser:pwuser /workspace
result=0
docker exec "$container" python scripts/ctx_workflow.py run verify || result=$?
# Return the actual adapter's reports, including its failure evidence. Never synthesize receipts.
if ! docker cp "$container:/workspace/.ctx/." "$root/.ctx/"; then
    [ "$result" -ne 0 ] || result=1
fi
exit "$result"
