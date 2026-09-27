#!/usr/bin/env bash
# Install the pinned Chrome for Testing build and its matching chromedriver
# into $1 (default: $RUNNER_TEMP/cft), verified by SHA-256.
# To bump: pick a version from
#   https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions.json
# and update the three values below (sha256sum of each zip).
set -euo pipefail

CHROME_VERSION="154.0.8037.57"
CHROME_SHA256="ceee2972074d441ea7c4ba8bcc0eaab77e7e87680f6653d73d3065851fe10302"
DRIVER_SHA256="48edfc7f6e02ed85c45357110f18a54a82d8993b908cc9bfff9517b12abc96d9"

dest="${1:-${RUNNER_TEMP:-/tmp}/cft}"
base="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64"
mkdir -p "$dest"
cd "$dest"
curl -sSfL --retry 3 -o chrome.zip "$base/chrome-linux64.zip"
curl -sSfL --retry 3 -o chromedriver.zip "$base/chromedriver-linux64.zip"
# stdout is reserved for the KEY=value lines at the end ($GITHUB_ENV).
echo "$CHROME_SHA256  chrome.zip" | sha256sum -c - >&2
echo "$DRIVER_SHA256  chromedriver.zip" | sha256sum -c - >&2
unzip -q -o chrome.zip
unzip -q -o chromedriver.zip
rm -f chrome.zip chromedriver.zip
echo "CHROME_BIN=$dest/chrome-linux64/chrome"
echo "CHROMEDRIVER_BIN=$dest/chromedriver-linux64/chromedriver"
echo "CHROME_VERSION=$CHROME_VERSION"
