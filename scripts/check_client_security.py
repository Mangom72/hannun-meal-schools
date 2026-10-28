#!/usr/bin/env python3
"""Check current client output for accidental server-key injection without printing credentials."""
import argparse
import os
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parent.parent


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--apk',type=Path)
    p.add_argument('--pages',type=Path,default=ROOT/'pages')
    a=p.parse_args()
    key=os.environ.get('NEIS_API_KEY','').encode()
    if a.apk:
        with zipfile.ZipFile(a.apk) as archive:
            for name in archive.namelist():
                data=archive.read(name)
                if b'NEIS_API_KEY' in data or (key and key in data):
                    raise SystemExit('Server-key material detected in APK. Refusing client distribution.')
    for path in a.pages.rglob('*'):
        if path.is_file():
            data=path.read_bytes()
            if b'NEIS_API_KEY' in data or (key and key in data):
                raise SystemExit('Server-key material detected in Pages output. Refusing publication.')
    print('Client security check passed: no server-key field or supplied secret in checked outputs.')


if __name__=='__main__':
    main()
