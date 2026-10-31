#!/usr/bin/env python3
"""Use the hash-pinned shared SP11 7.3 installer from the audio checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent


def shared_recipe(audio_repo, lock_path=HERE/'shared-release.json'):
    lock = json.loads(Path(lock_path).read_text())
    root = Path(audio_repo).resolve()
    for name, digest in lock['audio_files'].items():
        candidate = root/name
        if not candidate.is_file() or not candidate.resolve().is_relative_to(root):
            raise ValueError('missing shared recipe file: '+name)
        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError('shared recipe differs: '+name+'; use audio commit '+lock['audio_commit'])
    recipe = root/'recipes/sp11-7.3'
    if json.loads((recipe/'release-lock.json').read_text())['recipe_id'] != lock['recipe_id']:
        raise ValueError('different audio/touch release selected')
    return recipe/'recipe.py'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio-repo', required=True, type=Path)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    tool = shared_recipe(args.audio_repo)
    forwarded = args.arguments
    if forwarded and forwarded[0] == '--':
        forwarded = forwarded[1:]
    if not forwarded:
        forwarded = ['--help']
    return subprocess.call([sys.executable, str(tool), *forwarded])


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError) as error:
        raise SystemExit('SP11 shared recipe refused: '+str(error))
