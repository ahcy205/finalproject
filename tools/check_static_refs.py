"""스냅샷 화면과 CSS의 url(...)이 참조하는 /static/ 파일이 모두 실제로 있는지 검사한다.

    python tools/check_static_refs.py tools/snapshots/after

CSS 안의 폰트·이미지 경로는 화면에서 실제로 쓰일 때만 브라우저가 요청하므로,
여기서 "없음"으로 나와도 실제 404가 아닐 수 있다. 확인은 개발 서버 로그의 404로 한다.
"""
import argparse
import os
import re
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_ROOT = os.path.join(PROJECT, 'static')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('snapshot_dir', help='snapshot.py로 만든 폴더')
    snaps = parser.parse_args().snapshot_dir

    refs = {}
    for name in os.listdir(snaps):
        with open(os.path.join(snaps, name), encoding='utf-8') as f:
            for path in re.findall(r'["\'(]/static/([^"\'()?#\s]+)', f.read()):
                refs.setdefault(path, f'화면 {name}')

    for folder, _, files in os.walk(STATIC_ROOT):
        for name in files:
            if not name.endswith('.css'):
                continue
            css = os.path.join(folder, name)
            with open(css, encoding='utf-8', errors='replace') as f:
                text = f.read()
            for url in re.findall(r'url\(\s*[\'"]?([^\'")]+)[\'"]?\s*\)', text):
                if url.startswith(('data:', 'http:', 'https:', '//', '#')):
                    continue
                target = os.path.normpath(os.path.join(folder, url.split('?')[0].split('#')[0]))
                rel = os.path.relpath(target, STATIC_ROOT).replace(os.sep, '/')
                refs.setdefault(rel, f'CSS {os.path.relpath(css, STATIC_ROOT)}')

    missing = sorted((p, src) for p, src in refs.items() if not os.path.exists(os.path.join(STATIC_ROOT, p)))
    print(f'참조된 정적 파일 {len(refs)}개, 없는 파일 {len(missing)}개')
    for path, source in missing:
        print(f'  없음: {path}  ({source})')
    return 0 if not missing else 1


if __name__ == '__main__':
    sys.exit(main())
