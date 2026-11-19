"""Public service references, independent of simulated staff assignment."""
import csv
import re
from pathlib import Path


def filter_services(request, directory=None):
    """Filter requested service types and coverage; unknown access stays reviewable.

    request uses the existing server fields: escort, outbound, return_trip,
    wheelchair, district and hospital_district. No availability is inferred.
    """
    path = Path(directory) if directory else Path(__file__).with_name('carevisit_services.csv')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        entries = list(csv.DictReader(stream))
    result = []
    normalize = lambda value: str(value or '').strip().replace('區', '區')
    for entry in entries:
        kind = entry['service_type']
        if kind == 'escort':
            wanted = request.get('escort')
            district = request.get('hospital_district')
        elif kind == 'transport':
            wanted = request.get('outbound') or request.get('return_trip')
            district = request.get('district')
        else:
            continue
        if not wanted:
            continue
        coverage = {normalize(x) for x in re.split(r'[,，、;；|/]', entry['coverage'])}
        if district and '全港' not in coverage and normalize(district) not in coverage:
            continue
        if kind == 'transport' and request.get('wheelchair') and entry['wheelchair_onboard'] == 'no':
            continue
        result.append(entry)
    return result
