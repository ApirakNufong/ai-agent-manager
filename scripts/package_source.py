"""Package reviewable source and the built frontend, excluding local data and secrets."""
from pathlib import Path
import zipfile

root=Path(__file__).resolve().parents[1]
archive=root.parent/'ai-agent-manager-source.zip'
skip={'.git','.venv','.venv312','.tools','.python','.uv-cache','.npm-cache','.browser-tools','node_modules','__pycache__','.pytest_cache','data','artifacts'}
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
    count=0
    for file in root.rglob('*'):
        relative=file.relative_to(root)
        if not file.is_file() or any(part in skip for part in relative.parts) or file.name=='.env' or file.suffix=='.log': continue
        output.write(file,Path('ai-agent-manager')/relative)
        count+=1
print(f'Packaged {count} files: {archive.name} ({archive.stat().st_size:,} bytes)')
