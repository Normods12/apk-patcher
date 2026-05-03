#!/usr/bin/env python3
import argparse
import re
import shutil
import subprocess
import zipfile
from pathlib import Path


DEX_NAME_RE = re.compile(r"^classes(\d*)\.dex$")


def dex_index(name: str) -> int:
    match = DEX_NAME_RE.match(name)
    if not match:
        return -1
    suffix = match.group(1)
    return 1 if suffix == "" else int(suffix)


def find_last_dex(apk_path: Path) -> str:
    with zipfile.ZipFile(apk_path, "r") as zip_in:
        dex_names = [item.filename for item in zip_in.infolist() if DEX_NAME_RE.match(item.filename)]
    if not dex_names:
        raise RuntimeError(f"No classes*.dex found in {apk_path.name}")
    return max(dex_names, key=dex_index)


def replace_last_dex(apk_path: Path, payload_dex: Path, output_path: Path) -> str:
    target_dex_name = find_last_dex(apk_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(apk_path, "r") as zip_in:
        with zipfile.ZipFile(output_path, "w") as zip_out:
            for item in zip_in.infolist():
                if item.filename == target_dex_name:
                    payload_bytes = payload_dex.read_bytes()
                    replaced = zipfile.ZipInfo(filename=item.filename, date_time=item.date_time)
                    replaced.compress_type = item.compress_type
                    replaced.external_attr = item.external_attr
                    replaced.internal_attr = item.internal_attr
                    replaced.create_system = item.create_system
                    replaced.flag_bits = item.flag_bits
                    zip_out.writestr(replaced, payload_bytes)
                else:
                    zip_out.writestr(item, zip_in.read(item.filename))

    return target_dex_name


def _first_existing(base_dir: Path, candidates: list[str]) -> Path:
    for name in candidates:
        candidate = base_dir / name
        if candidate.exists():
            return candidate
    return base_dir / candidates[0]


def resolve_default_paths(base_dir: Path) -> tuple[Path, Path, Path]:
    dex_dir = _first_existing(base_dir, ["dex-to-add", "Dex-to-add"])
    input_dir = _first_existing(base_dir, ["input-apks", "Input-apk"])
    output_dir = _first_existing(base_dir, ["output-apks", "Output-apk"])
    return dex_dir, input_dir, output_dir


def sign_apk(apk_path: Path, output_dir: Path, signer_path: Path) -> bool:
    if not signer_path.exists():
        print(f"[!] Signer not found at {signer_path}")
        return False
    
    print(f"[*] Signing {apk_path.name}...")
    try:
        # Use --overwrite to sign in-place without producing new files with suffixes
        cmd = [
            "java", "-jar", str(signer_path),
            "-a", str(apk_path),
            "--overwrite"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and "either provide out path or overwrite" not in result.stdout:
            print(f"[OK] Signed {apk_path.name}")
            return True
        else:
            error_msg = result.stderr or result.stdout
            print(f"[!] Signing failed for {apk_path.name}: {error_msg}")
            return False
    except Exception as e:
        print(f"[!] Error running signer: {e}")
        return False


def run(payload_dex: Path, input_dir: Path, output_dir: Path, signer_path: Path = None) -> None:
    if not payload_dex.exists():
        raise FileNotFoundError(f"Payload dex not found: {payload_dex}")
    if not input_dir.exists():
        raise FileNotFoundError(f"Input folder not found: {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    apk_files = sorted([path for path in input_dir.iterdir() if path.is_file() and path.suffix.lower() == ".apk"])
    if not apk_files:
        raise RuntimeError(f"No APK files found in {input_dir}")

    for apk_path in apk_files:
        output_path = output_dir / apk_path.name
        replaced_name = replace_last_dex(apk_path, payload_dex, output_path)
        print(f"[OK] {apk_path.name} -> replaced {replaced_name} -> {output_path.name}")
        
        if signer_path:
            sign_apk(output_path, output_dir, signer_path)


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    default_dex_dir, default_input_dir, default_output_dir = resolve_default_paths(base_dir)
    dex_candidates = sorted(default_dex_dir.glob("classes*.dex"))
    default_payload = dex_candidates[0] if dex_candidates else (default_dex_dir / "classes9.dex")

    parser = argparse.ArgumentParser(description="Replace last classes*.dex in APKs with a constant payload dex.")
    parser.add_argument("--payload-dex", type=Path, default=default_payload, help="Path to constant dex to inject")
    parser.add_argument("--input-dir", type=Path, default=default_input_dir, help="Input APK folder")
    parser.add_argument("--output-dir", type=Path, default=default_output_dir, help="Output APK folder")
    parser.add_argument("--signer", type=Path, help="Path to uber-apk-signer.jar")
    parser.add_argument("--clean-output", action="store_true", help="Delete existing APK files in output folder first")
    args = parser.parse_args()

    if args.clean_output and args.output_dir.exists():
        for file_path in args.output_dir.glob("*.apk"):
            file_path.unlink(missing_ok=True)

    # Resolve signer path
    signer = args.signer
    if not signer:
        # Check standard location relative to UNIVERSAL_PATCHER_DIR if set
        # For now, we'll try the hardcoded path from the old flow as a fallback
        potential_signer = Path(r"C:\Users\smadd\Desktop\Cursor\UniversalPatcher\tools\uber-apk-signer.jar")
        if potential_signer.exists():
            signer = potential_signer

    run(args.payload_dex, args.input_dir, args.output_dir, signer)


if __name__ == "__main__":
    main()
