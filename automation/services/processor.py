import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Tuple

from automation.config import LOCKS_DIR, OUTPUT_DIR, PATCHER_COMMAND, UNIVERSAL_PATCHER_DIR

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def _run_command(command: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd else None,
    )


@contextmanager
def _patcher_lock(timeout_seconds: int = 1800):
    lock_path = LOCKS_DIR / "universal_patcher.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if not lock_path.exists() or lock_path.stat().st_size == 0:
        with open(lock_path, "wb") as seed_file:
            seed_file.write(b"0")
    start = time.monotonic()

    with open(lock_path, "r+b") as lock_file:
        while True:
            try:
                if os.name == "nt":
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() - start > timeout_seconds:
                    raise TimeoutError("Timed out waiting for UniversalPatcher lock")
                time.sleep(1)

        try:
            yield
        finally:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _process_with_universal_patcher(input_file: Path, output_file: Path) -> Tuple[Path, str]:
    patcher_dir = Path(UNIVERSAL_PATCHER_DIR).resolve()
    input_dir = patcher_dir / "input_apks"
    output_dir = patcher_dir / "output_apks"

    if not patcher_dir.exists():
        raise RuntimeError(f"UNIVERSAL_PATCHER_DIR not found: {patcher_dir}")

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    source_file = input_file.resolve()
    is_archive = source_file.suffix.lower() in [".xapk", ".apks", ".zip"]

    if not is_archive and source_file.suffix.lower() != ".apk":
        raise RuntimeError(f"UniversalPatcher only supports .apk or .xapk files, but got {source_file.suffix} ({source_file.name})")

    # Clear patcher input/output dirs
    for existing in input_dir.glob("*.apk"):
        existing.unlink(missing_ok=True)
    for existing in output_dir.glob("*.apk"):
        existing.unlink(missing_ok=True)

    temp_extract_dir = None
    if is_archive:
        import zipfile
        temp_extract_dir = patcher_dir / "temp_xapk_extract"
        if temp_extract_dir.exists():
            shutil.rmtree(temp_extract_dir)
        temp_extract_dir.mkdir(parents=True, exist_ok=True)
        
        with zipfile.ZipFile(source_file, "r") as zf:
            zf.extractall(temp_extract_dir)
            
        extracted_apks = list(temp_extract_dir.rglob("*.apk"))
        if not extracted_apks:
            raise RuntimeError(f"No .apk files found inside archive {source_file.name}")
            
        for apk in extracted_apks:
            shutil.copy2(apk, input_dir / apk.name)
    else:
        # Standard .apk processing
        staged_source: Path | None = None
        if source_file.parent == input_dir.resolve():
            staged_source = source_file.parent.parent / f"_staged_{source_file.name}"
            shutil.copy2(source_file, staged_source)
            source_file = staged_source

        patcher_input = input_dir / source_file.name
        shutil.copy2(source_file, patcher_input)

        if staged_source and staged_source.exists():
            staged_source.unlink(missing_ok=True)

    # Run the patcher
    result = _run_command("py fast_patcher.py", cwd=patcher_dir)
    if result.returncode != 0:
        stderr = result.stderr.strip() or "fast_patcher.py failed without stderr"
        raise RuntimeError(stderr)

    stdout_text = result.stdout or ""
    if "[+] Hook found in" not in stdout_text:
        stdout_tail = stdout_text.strip()[-700:]
        raise RuntimeError(
            "fast_patcher.py completed but no hooks were successfully applied. "
            "App is likely incompatible with UniversalPatcher. "
            f"Patcher output: {stdout_tail}"
        )

    produced = sorted(output_dir.glob("*.apk"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not produced:
        raise RuntimeError("fast_patcher.py completed but no output APK was produced in output_apks.")

    # Reconstruct output
    if is_archive:
        # Replace original extracted apks with the newly signed/patched ones
        for patched_apk in produced:
            # Find the corresponding original inside temp_extract_dir
            for orig_apk in temp_extract_dir.rglob("*.apk"):
                if orig_apk.name == patched_apk.name:
                    shutil.copy2(patched_apk, orig_apk)
                    break
                    
        # Zip back up to output_file
        import zipfile
        with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(temp_extract_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(temp_extract_dir)
                    zf.write(file_path, arcname)
                    
        shutil.rmtree(temp_extract_dir)
    else:
        # Just copy the single produced apk
        shutil.copy2(produced[0], output_file)

    message = stdout_text.strip() or "Processed via UniversalPatcher"
    return output_file, message


def process_file(input_file: Path, output_filename: str | None = None) -> Tuple[Path, str]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    input_stem = input_file.stem
    output_file = OUTPUT_DIR / (output_filename or f"{input_stem}_processed.apk")

    if UNIVERSAL_PATCHER_DIR:
        with _patcher_lock():
            return _process_with_universal_patcher(input_file, output_file)

    if "{input_file}" in PATCHER_COMMAND:
        command = PATCHER_COMMAND.format(input_file=str(input_file))
    else:
        command = f"{PATCHER_COMMAND} \"{input_file}\""

    result = _run_command(command)

    if result.returncode != 0:
        stderr = result.stderr.strip() or "patcher command failed without stderr output"
        raise RuntimeError(stderr)

    # Fallback for patchers that do in-place processing or do not produce an output artifact path.
    if not output_file.exists():
        shutil.copy2(input_file, output_file)

    message = result.stdout.strip() or "Processed successfully"
    return output_file, message
