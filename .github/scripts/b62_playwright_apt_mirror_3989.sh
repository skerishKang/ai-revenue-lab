#!/usr/bin/env bash
# #3989: B62 Linux Playwright APT download mirror pilot.
# Swap *only* Ubuntu's archive mirror on ephemeral Ubuntu 24.04 Actions runners;
# ubuntu-security / Microsoft package sources, package signatures and the
# required Playwright install --with-deps chromium step remain unchanged.
set -euo pipefail

if [[ ! -r /etc/os-release ]]; then
  echo 'B62_APT_MIRROR=HOST_DEFAULT_NO_OS_RELEASE'
  exit 0
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}-${VERSION_ID:-}" != 'ubuntu-24.04' ]]; then
  echo 'B62_APT_MIRROR=HOST_DEFAULT_UNSUPPORTED_OS'
  exit 0
fi

mirror_file=/etc/apt/apt-mirrors.txt
old_host='azure.archive.ubuntu.com/ubuntu/'
new_host='archive.ubuntu.com/ubuntu/'
if [[ ! -f "$mirror_file" ]] || ! grep -Fq "$old_host" "$mirror_file"; then
  echo 'B62_APT_MIRROR=HOST_DEFAULT_NOT_AZURE'
  exit 0
fi

# This affects only Ubuntu archive/updates/backports (the hosted-runner mirror
# list), not apt package selection. apt still validates Ubuntu signatures.
sudo sed -i "s|${old_host}|${new_host}|g" "$mirror_file"
if grep -Fq "$old_host" "$mirror_file" || ! grep -Fq "$new_host" "$mirror_file"; then
  echo 'B62_APT_MIRROR=CONFIGURATION_FAILED'
  exit 1
fi
echo 'B62_APT_MIRROR=OFFICIAL_UBUNTU_ARCHIVE'
echo 'B62_APT_INSTALL_CONTRACT=PLAYWRIGHT_WITH_DEPS_UNCHANGED'
