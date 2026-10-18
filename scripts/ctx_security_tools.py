"""Install the pinned Trivy binary after verifying its reviewed SHA256 checksum."""
import argparse
import hashlib
import io
from pathlib import Path
import platform
import tarfile
import urllib.request

PINS = {
    "trivy": ("0.76.0", "aquasecurity/trivy", {
        "Linux": ("trivy_0.76.0_Linux-64bit.tar.gz", "e24b1c51293c1b15e4ba8d45bbc7891ba053f90278ec2698f3562c993e145fe7"),
        "Darwin": ("trivy_0.76.0_macOS-ARM64.tar.gz", "e7ec0d21fe842553f59af99aba2efbcc822369fbaed27019c575408b6d135fce"),
    }),
}


def binary(data, name, filename, checksum):
    if hashlib.sha256(data).hexdigest() != checksum:
        raise ValueError("tool checksum differs from reviewed pin")
    # Extract one regular file only. Never trust archive paths or symbolic links.
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        info = archive.getmember(name)
        if not info.isfile() or info.size > 300_000_000:
            raise ValueError("invalid binary archive member")
        return archive.extractfile(info).read()


def install(name, destination):
    system = platform.system()
    if (system, platform.machine()) not in {("Linux", "x86_64"), ("Darwin", "arm64")}:
        raise ValueError("use the reviewed Linux amd64 CI runner or macOS arm64 host")
    version, repository, variants = PINS[name]
    filename, checksum = variants[system]
    url = f"https://github.com/{repository}/releases/download/v{version}/{filename}"
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(300_000_001)
    if len(data) > 300_000_000:
        raise ValueError("tool download exceeds size limit")
    payload = binary(data, name, filename, checksum)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / name
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError("symlink install destination refused")
    target.write_bytes(payload)
    target.chmod(0o755)
    print(f"Installed {name} {version} after SHA256 verification")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tools", nargs="+", choices=sorted(PINS))
    args = parser.parse_args()
    for tool in args.tools:
        install(tool, Path(__file__).resolve().parents[1] / ".ctx/bin")
