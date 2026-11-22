"""Start, inspect, and stop the native background-service wrapper in one owner process."""
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import local_service


def main():
    args=SimpleNamespace(api_port=8040,booking_port=8042,web_port=3040,demo=False)
    try:
        assert local_service.start(args)==0
        assert local_service.status()==0
    finally:
        assert local_service.stop()==0
    assert local_service.status()==1
    print('PASS: native service wrapper started, reported healthy, stopped its owned tree, and cleared state.')


if __name__=='__main__': main()
