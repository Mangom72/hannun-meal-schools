import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

spec = importlib.util.spec_from_file_location('directory', Path(__file__).resolve().parents[1] / 'sync_school_directory.py')
directory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(directory)


def row(code, name='한빛고등학교', office='B10', kind='고등학교'):
    return dict(ATPT_OFCDC_SC_CODE=office, SD_SCHUL_CODE=code, SCHUL_NM=name, SCHUL_KND_SC_NM=kind, LCTN_SC_NM='서울특별시', ORG_RDNMA='서울 주소')


def page(rows, total):
    return dict(schoolInfo=[dict(head=[dict(list_total_count=total), dict(RESULT=dict(CODE='INFO-000'))]), dict(row=rows)])


class SchoolDirectoryTests(unittest.TestCase):
    def test_pagination_duplicates_and_duplicate_names_keep_identity(self):
        pages = [page([row('7010057'), row('7010057')], 3), page([row('7010058', office='J10')], 3)]
        calls = []
        def fetch(url):
            calls.append(parse_qs(urlsplit(url).query))
            return pages.pop(0)
        rows = directory.collect('private-test-key', fetch)
        self.assertEqual(2, len(rows))
        self.assertEqual(rows[0][2], rows[1][2])
        self.assertNotEqual(rows[0][:2], rows[1][:2])
        self.assertEqual(['2'], calls[1]['pIndex'])

    def test_nationwide_requires_all_offices_and_types(self):
        rows = [[o, f'{i:07}', '학교', t, '지역', '주소'] for i, (o, t) in enumerate((o, t) for o in directory.OFFICES for t in directory.TYPES)]
        directory.validate(rows, minimum=1)
        with self.assertRaises(directory.DirectoryError):
            directory.validate(rows[:3], minimum=1)

    def test_incomplete_or_failed_generation_preserves_working_index(self):
        with tempfile.TemporaryDirectory() as path:
            rows = [['B10','7010057','학교','고등학교','서울','주소']]
            directory.publish(rows, path, minimum=1, require_nationwide=False)
            before = {p.name:p.read_bytes() for p in Path(path).iterdir()}
            with self.assertRaises(directory.DirectoryError):
                directory.publish([], path, minimum=1, require_nationwide=False)
            self.assertEqual(before, {p.name:p.read_bytes() for p in Path(path).iterdir()})

    def test_repeated_pages_changed_total_and_auth_failures_are_errors(self):
        for pages in [[page([row('7010057')],3)]*3, [page([row('7010057')],3),page([row('7010058')],2)], [dict(RESULT=dict(CODE='ERROR-290'))]]:
            with self.assertRaises(directory.DirectoryError):
                directory.collect('key', lambda _:pages.pop(0))

    def test_hash_and_index_name_match_compact_payload(self):
        with tempfile.TemporaryDirectory() as path:
            index=directory.publish([['B10','7010057','학교','고등학교','서울','주소']],path,minimum=1,require_nationwide=False)
            data=(Path(path)/index['file']).read_bytes()
            self.assertEqual(index['sha256'], directory.hashlib.sha256(data).hexdigest())
            self.assertEqual(1,json.loads(data)['schemaVersion'])

    def test_secret_is_not_printed_on_http_failure(self):
        error=RuntimeError('https://open.neis.go.kr/hub/schoolInfo?KEY=private-secret')
        with tempfile.TemporaryDirectory() as path, patch.dict(os.environ,{'NEIS_API_KEY':'private-secret'}), patch('sys.argv',['sync','--output',path]), patch.object(directory,'download',side_effect=error), patch.object(directory,'collect',side_effect=error), patch('sys.stderr',new_callable=io.StringIO) as stderr:
            self.assertEqual(1,directory.main())
            self.assertNotIn('private-secret',stderr.getvalue())

    def test_large_unexpected_drop_rejected(self):
        with self.assertRaises(directory.DirectoryError):
            directory.validate([['B10','7010057','학교','고등학교','서울','주소']],previous_count=100,minimum=1,require_nationwide=False)


if __name__ == '__main__':
    unittest.main()
