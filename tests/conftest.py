import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MINI_STEP = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('demo'),'2;1');
FILE_NAME('{fname}','{ts}',('author'),('org'),'pre 1.0','{system}','');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN {{ 1 0 10303 214 1 1 1 1 }}'));
ENDSEC;
DATA;
#{a} = PRODUCT('{pid}','{pname}','{pdesc}',(#{b}));
#{b} = PRODUCT_CONTEXT('',#{c},'mechanical');
#{c} = APPLICATION_CONTEXT('automotive design');
#{d} = CARTESIAN_POINT('',({x},0.,0.));
#{e} = ( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNIT_ASSIGNED_CONTEXT((#{f})) REPRESENTATION_CONTEXT('Context #1','3D Context') );
#{f} = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );
ENDSEC;
END-ISO-10303-21;
"""


def make_step(fname="a.step", ts="2024-01-01T00:00:00", system="SysA", pid="PA-1", pname="Bracket",
              pdesc="", x="1.5", base=1):
    ids = dict(zip("abcdef", range(base, base + 6)))
    return MINI_STEP.format(fname=fname, ts=ts, system=system, pid=pid, pname=pname, pdesc=pdesc, x=x, **ids)


@pytest.fixture
def mini_step():
    return make_step
