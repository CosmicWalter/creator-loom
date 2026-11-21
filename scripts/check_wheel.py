"""Ensure the installable package contains the actual workbench assets."""

from pathlib import Path
import sys
import zipfile

folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dist")
wheels = list(folder.glob("creator_loom-*.whl"))
if not wheels:
    raise SystemExit("No Creator Loom wheel found")
for wheel in wheels:
    with zipfile.ZipFile(wheel) as archive:
        for name in ["creator_loom/static/index.html", "creator_loom/static/app.js", "creator_loom/static/app.css", "creator_loom/static/timeline.js"]:
            if name not in archive.namelist() or not archive.read(name):
                raise SystemExit("Workbench asset missing from package: " + name)
print("Installable wheel contains the workbench HTML, JavaScript and styles")
