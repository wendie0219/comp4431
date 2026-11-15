import csv
import tempfile
import unittest
from pathlib import Path
from service_directory import filter_services


class DirectoryTests(unittest.TestCase):
    def test_scope_access_and_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'services.csv'
            with path.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['service_id', 'service_type', 'coverage', 'wheelchair_onboard'])
                writer.writeheader()
                for sid, kind, area, access in [
                    ('local', 'transport', '南區', 'yes'),
                    ('unknown', 'transport', '全港', 'unknown'),
                    ('inaccessible', 'transport', '全港', 'no'),
                    ('other', 'transport', '沙田區', 'yes'),
                    ('escort', 'escort', '沙田區', 'not_applicable')]:
                    writer.writerow(dict(service_id=sid, service_type=kind, coverage=area, wheelchair_onboard=access))
            request = dict(escort=True, outbound=True, return_trip=False, wheelchair=True, district='南区', hospital_district='沙田区')
            self.assertEqual([x['service_id'] for x in filter_services(request, path)], ['local', 'unknown', 'escort'])
            request.update(escort=False, outbound=False)
            self.assertEqual(filter_services(request, path), [])


if __name__ == '__main__':
    unittest.main()
