#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "The macOS executor must be built on macOS." >&2
  exit 1
fi

repository_root="$(cd "$(dirname "$0")/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
output_directory="${OUTPUT_DIRECTORY:-$repository_root/dist/local-executor-macos}"
build_directory="$repository_root/build/local-executor-macos"
staging_directory="$build_directory/dmg"
application_name="Topstep Local Executor.app"
architecture="$(uname -m)"
dmg_path="$output_directory/Topstep-Local-Executor-${architecture}.dmg"

export PYTHONHASHSEED=0
export SOURCE_DATE_EPOCH=1767225600

"$python_bin" -m pip install --disable-pip-version-check \
  -r "$repository_root/local_executor/requirements.lock"
"$python_bin" -m pip install --disable-pip-version-check \
  -r "$repository_root/local_executor/requirements-build.lock"

"$python_bin" -m PyInstaller \
  --noconfirm \
  --clean \
  --workpath "$build_directory/pyinstaller" \
  --distpath "$output_directory" \
  "$repository_root/local_executor/macos_executor.spec"

app_path="$output_directory/$application_name"
if [[ ! -d "$app_path" ]]; then
  echo "Expected macOS app bundle was not produced." >&2
  exit 1
fi

if [[ -n "${MACOS_CODESIGN_IDENTITY:-}" ]]; then
  codesign --force --deep --options runtime --timestamp \
    --sign "$MACOS_CODESIGN_IDENTITY" "$app_path"
else
  # Ad-hoc signing makes the CI artifact structurally testable. Release-manifest
  # verification still prevents it from becoming mutation capable.
  codesign --force --deep --sign - "$app_path"
fi
codesign --verify --deep --strict "$app_path"

rm -rf "$staging_directory"
mkdir -p "$staging_directory"
cp -R "$app_path" "$staging_directory/$application_name"
ln -s /Applications "$staging_directory/Applications"
mkdir -p "$output_directory"
rm -f "$dmg_path"
hdiutil create -volname "Topstep Local Executor" -srcfolder "$staging_directory" \
  -ov -format UDZO "$dmg_path"

if [[ -n "${MACOS_NOTARYTOOL_PROFILE:-}" ]]; then
  xcrun notarytool submit "$dmg_path" \
    --keychain-profile "$MACOS_NOTARYTOOL_PROFILE" --wait
  xcrun stapler staple "$dmg_path"
fi

artifact_hash="$(shasum -a 256 "$dmg_path" | awk '{print $1}')"
printf '{"artifact":"%s","sha256":"%s"}\n' "$dmg_path" "$artifact_hash"
