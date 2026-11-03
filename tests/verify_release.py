"""Offline integrity and theme/restore checks for both brands and firmware profiles."""

from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parent.parent


def verify_brand(brand: str) -> None:
    app = ROOT / brand
    sys.path.insert(0, str(app))
    from theme import build_theme, load_profile  # noqa: PLC0415
    import recovery  # noqa: PLC0415

    for version in ("V9.3.10P7N6", "V9.3.10P7N7"):
        profile = load_profile(version)
        theme = build_theme(profile, f"Bem-vindo, cliente {brand}.", app / "resources/Logo_ZTE.png")
        assert len(theme.files) == 7
        assert recovery.overlay_files(theme.block, profile) == theme.files
        stock = recovery.load_stock_files(profile)
        _, payload, restored = recovery.build_restore_payload(theme.block, profile, stock)
        assert payload and recovery.overlay_files(restored, profile) == stock
        print(f"{brand} {version}: tema e restauração OK")

    archive = app / f"{brand}_Windows_x64.zip"
    with ZipFile(archive) as bundle:
        assert any(name.endswith(".exe") for name in bundle.namelist())
        assert bundle.testzip() is None
    print(f"{brand}: pacote Windows íntegro")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        verify_brand(sys.argv[1])
    else:
        for name in ("Atuamax", "Netflex"):
            subprocess.run([sys.executable, str(Path(__file__).resolve()), name], check=True)
