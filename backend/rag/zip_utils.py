"""Extração segura de zip (protege contra zip-slip e zip-bomb)."""

from __future__ import annotations

import zipfile
from pathlib import Path


class ZipRejected(ValueError):
    pass


def safe_extract_zip(zip_path: str, dest: str, max_bytes: int, max_files: int) -> int:
    """Extrai em `dest` e devolve a quantidade de arquivos. Levanta ZipRejected se for suspeito."""
    root = Path(dest).resolve()
    root.mkdir(parents=True, exist_ok=True)
    count = 0
    total = 0
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ZipRejected("Arquivo zip inválido.") from exc

    with archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if len(infos) > max_files:
            raise ZipRejected(f"Zip com {len(infos)} arquivos (limite {max_files}).")
        if sum(i.file_size for i in infos) > max_bytes:
            raise ZipRejected("Conteúdo descompactado acima do limite permitido.")
        for info in infos:
            name = info.filename.replace("\\", "/")
            target = (root / name).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ZipRejected(f"Caminho suspeito no zip: {info.filename}") from exc
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as out:
                while chunk := src.read(1024 * 256):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ZipRejected("Conteúdo descompactado acima do limite permitido.")
                    out.write(chunk)
            count += 1
    return count


def single_top_folder(dest: str) -> str:
    """Se o zip tem uma única pasta na raiz (padrão do GitHub), devolve o caminho dela."""
    entries = [p for p in Path(dest).iterdir()]
    if len(entries) == 1 and entries[0].is_dir():
        return str(entries[0])
    return dest
