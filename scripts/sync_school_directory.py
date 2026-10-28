#!/usr/bin/env python3
"""Generate an atomic, content-addressed nationwide NEIS directory. No third-party dependencies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime, timezone
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

OFFICES = {'B10','C10','D10','E10','F10','G10','H10','I10','J10','K10','M10','N10','P10','Q10','R10','S10','T10'}
TYPES = {'초등학교', '중학교', '고등학교'}
PUBLIC_USER_AGENT = 'HannunMeal-DataSetup/1.2'


class DirectoryError(Exception):
    def __init__(self, message, safe_details=None):
        super().__init__(message)
        self.safe_details = safe_details


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download_bytes(url):
    # NEIS selects JSON with Type=json; Accept: application/json returns HTTP 500.
    with build_opener(NoRedirect).open(Request(url, headers={'Accept': '*/*', 'User-Agent': PUBLIC_USER_AGENT}), timeout=30) as response:
        if response.status != 200:
            raise DirectoryError('HTTP failure')
        data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise DirectoryError('Response too large')
        return data


def download(url):
    return json.loads(download_bytes(url))


def page(root):
    if 'RESULT' in root:
        if root['RESULT'].get('CODE') == 'INFO-200':
            return 0, []
        raise DirectoryError('NEIS result failure')
    sections = root.get('schoolInfo')
    if not isinstance(sections, list):
        raise DirectoryError('Missing schoolInfo')
    head = [h for part in sections for h in part.get('head', [])]
    codes = [h['RESULT'].get('CODE') for h in head if 'RESULT' in h]
    total = next((h['list_total_count'] for h in head if 'list_total_count' in h), None)
    rows = [row for part in sections for row in part.get('row', [])]
    if not codes or any(c != 'INFO-000' for c in codes) or not isinstance(total, int) or not 0 <= total <= 40000 or (total and not rows):
        raise DirectoryError('Invalid pagination')
    return total, rows


def collect(key, fetch=download, *, stats=None):
    if not key.strip():
        raise DirectoryError('NEIS_API_KEY is required')
    result, fingerprints, read, expected = {}, set(), 0, None
    for index in range(1, 41):
        params = dict(KEY=key, Type='json', pIndex=index, pSize=1000)
        total, rows = page(fetch('https://open.neis.go.kr/hub/schoolInfo?' + urlencode(params)))
        if expected is not None and total != expected:
            raise DirectoryError('Dataset changed during pagination')
        expected = total
        fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).digest()
        if rows and fingerprint in fingerprints:
            raise DirectoryError('Repeated page')
        fingerprints.add(fingerprint)
        read += len(rows)
        for row in rows:
            if row.get('SCHUL_KND_SC_NM') not in TYPES:
                continue
            values = [row.get(k, '') or '' for k in ['ATPT_OFCDC_SC_CODE','SD_SCHUL_CODE','SCHUL_NM','SCHUL_KND_SC_NM','LCTN_SC_NM','ORG_RDNMA']]
            values = [value.strip() if isinstance(value,str) else value for value in values]
            values[5] = values[5] or values[4] # Region-only fallback when NEIS omits a street address.
            if values[0] not in OFFICES:
                raise DirectoryError('Unsupported education office')
            if values[1] == '':
                # Some official directory rows have no NEIS lookup identity. Never invent one.
                if stats is not None:
                    stats['withoutSchoolCode'] = stats.get('withoutSchoolCode',0)+1
                continue
            if not isinstance(values[1],str) or not re.fullmatch(r'\d{7}', values[1]):
                raise DirectoryError('Invalid school code', {'isString':isinstance(values[1],str),'length':min(len(str(values[1])),1000),'asciiDigits':isinstance(values[1],str) and values[1].isascii() and values[1].isdigit()})
            for field_index, label in enumerate(['office','code','name','type','region','address']):
                if not isinstance(values[field_index],str) or not values[field_index].strip():
                    raise DirectoryError('Missing school '+label)
            values = [x.strip() for x in values]
            identity = tuple(values[:2])
            # Stable deduplication, regardless of upstream row ordering.
            result[identity] = min(result.get(identity, values), values)
        if read == total:
            return sorted(result.values(), key=lambda r: (r[0], r[1]))
        if read > total:
            raise DirectoryError('Pagination overrun')
    raise DirectoryError('Pagination limit')


def validate(rows, previous_count=0, minimum=10000, require_nationwide=True):
    if len(rows) < minimum or (previous_count and len(rows) < previous_count * .9):
        raise DirectoryError('Directory incomplete or unexpectedly smaller')
    if len({tuple(r[:2]) for r in rows}) != len(rows):
        raise DirectoryError('Duplicate identities')
    if require_nationwide and ({r[0] for r in rows} != OFFICES or {r[3] for r in rows} != TYPES):
        raise DirectoryError('Missing region or school type')


def publish(rows, output, previous_count=0, minimum=10000, require_nationwide=True, preserved=None):
    validate(rows, previous_count, minimum, require_nationwide)
    payload = json.dumps(dict(schemaVersion=1, schools=rows), ensure_ascii=False, separators=(',', ':')).encode()
    digest = hashlib.sha256(payload).hexdigest()
    filename = f'schools.{digest}.json'
    index = dict(schemaVersion=1, generatedAt=datetime.now(timezone.utc).isoformat(), count=len(rows), sha256=digest, file=filename)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # The immutable data file is complete before the index is atomically promoted.
    def atomic(name, data):
        with tempfile.NamedTemporaryFile(dir=output, delete=False) as f:
            temporary = Path(f.name)
            try:
                f.write(data); f.flush(); os.fsync(f.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        os.replace(temporary, output / name)
    for name, data in (preserved or {}).items():
        if not re.fullmatch(r'schools\.[a-f0-9]{64}\.json', name) or name != f'schools.{hashlib.sha256(data).hexdigest()}.json':
            raise DirectoryError('Invalid previous asset')
        atomic(name, data)
    atomic(filename, payload)
    atomic('schools-index.json', json.dumps(index, ensure_ascii=False, separators=(',', ':')).encode())
    return index


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, default=Path('pages'))
    p.add_argument('--previous-base', help='Existing HTTPS Pages base URL for completeness comparison')
    args = p.parse_args()
    stage = 'previous-cache'
    try:
        previous = 0
        preserved = {}
        local_index = args.output / 'schools-index.json'
        if local_index.exists():
            previous = json.loads(local_index.read_text())['count']
        elif args.previous_base:
            if not args.previous_base.startswith('https://'):
                raise DirectoryError('Previous base must use HTTPS')
            # 404 means first deployment; other failures must not skip the comparison silently.
            try:
                index = download(args.previous_base.rstrip('/') + '/schools-index.json')
                if not re.fullmatch(r'[a-f0-9]{64}', index['sha256']) or index['file'] != f"schools.{index['sha256']}.json":
                    raise DirectoryError('Invalid previous index')
                previous = index['count']
                preserved[index['file']] = download_bytes(args.previous_base.rstrip('/') + '/' + index['file'])
            except HTTPError as e:
                if e.code != 404: raise
        stage = 'neis-download'
        key = os.environ.get('NEIS_API_KEY', '')
        stats = {}
        rows = collect(key, stats=stats)
        if key and key in json.dumps(rows, ensure_ascii=False):
            raise DirectoryError('Credential appeared in upstream data')
        stage = 'validate-publish'
        index = publish(rows, args.output, previous, preserved=preserved)
        if stats.get('withoutSchoolCode'):
            print(f"Omitted {stats['withoutSchoolCode']} official rows without a NEIS school code; no lookup identities were invented.")
        print(f"Validated {index['count']} schools across 17 education offices; static directory ready.")
    except Exception as error:
        # URL/exception text may contain the query-string credential. Never print it or a traceback.
        reasons = {'Directory incomplete or unexpectedly smaller':'INCOMPLETE', 'Missing region or school type':'MISSING_REGION_OR_TYPE', 'Unsupported education office':'UNSUPPORTED_OFFICE', 'Invalid school code':'SCHOOL_CODE', 'Missing school region':'MISSING_SCHOOL_REGION', 'Missing school name':'MISSING_SCHOOL_NAME', 'Missing school address':'MISSING_SCHOOL_ADDRESS', 'Repeated page':'REPEATED_PAGE', 'Dataset changed during pagination':'DATASET_CHANGED', 'Pagination overrun':'PAGINATION_OVERRUN', 'Invalid pagination':'INVALID_PAGINATION', 'NEIS result failure':'NEIS_RESULT', 'NEIS_API_KEY is required':'MISSING_SECRET'}
        reason = ('HTTP_'+str(error.code)) if isinstance(error, HTTPError) and isinstance(error.code,int) else 'NETWORK' if isinstance(error,(URLError,TimeoutError)) else reasons.get(str(error),'VALIDATION') if isinstance(error,DirectoryError) else 'UNEXPECTED'
        if isinstance(error,HTTPError):
            error.close()
        details = json.dumps(error.safe_details) if isinstance(error,DirectoryError) and error.safe_details else ''
        print(f'School directory generation failed [stage={stage}; reason={reason}] {details}. Previous valid deployment and files are preserved.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
